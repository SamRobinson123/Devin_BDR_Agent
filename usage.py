"""Usage and spend tracking for the paid APIs the agent runs on.

Two very different data sources:

- Hunter publishes live plan quota on GET /v2/account, and that call is free, so
  searches/verifications left are always authoritative.
- Anthropic only publishes spend through the Admin API, which needs an
  organisation admin key (sk-ant-admin…) that is *not* the key the agent runs
  on. Without one we price a local ledger of token counts instead, so the tab is
  still useful on a plain API key.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

import settings_store
from db import init_db, record_usage_event, usage_grouped, usage_totals

SETTINGS_KEY = "usage"

DEFAULT_SETTINGS = {
    "anthropic_admin_key": "",
    "monthly_budget_usd": 0.0,
}

SECRET_FIELDS = ("anthropic_admin_key",)

HUNTER_ACCOUNT_URL = "https://api.hunter.io/v2/account"
HUNTER_UPGRADE_URL = "https://hunter.io/pricing"
ANTHROPIC_COST_URL = "https://api.anthropic.com/v1/organizations/cost_report"
ANTHROPIC_ADMIN_KEYS_URL = "https://console.anthropic.com/settings/admin-keys"
ANTHROPIC_USAGE_URL = "https://console.anthropic.com/settings/usage"

# USD per million tokens, from anthropic.com/pricing. Longest matching prefix wins.
MODEL_PRICING = {
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25},
    "claude-3-5-haiku": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
}
FALLBACK_PRICING = MODEL_PRICING["claude-sonnet-4"]

# The server-side web search tool bills per request: $10 / 1,000 searches.
WEB_SEARCH_USD = 0.01

QUOTA_LABELS = {
    "credits": "Credits",
    "searches": "Domain searches",
    "verifications": "Email verifications",
}


def merge_defaults(stored: dict | None) -> dict:
    return settings_store.merge_defaults(DEFAULT_SETTINGS, stored)


def redact(settings: dict) -> dict:
    return settings_store.redact(settings, SECRET_FIELDS)


def apply_update(stored: dict, update: dict) -> dict:
    return settings_store.apply_update(DEFAULT_SETTINGS, SECRET_FIELDS, stored, update)


def pricing_for(model: str | None) -> dict:
    name = (model or "").strip().lower()
    matches = [p for prefix, p in MODEL_PRICING.items() if name.startswith(prefix)]
    return matches[0] if matches else FALLBACK_PRICING


def token_cost(model: str | None, input_tokens: int = 0, output_tokens: int = 0,
               cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    price = pricing_for(model)
    return (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + cache_read_tokens * price["cache_read"]
        + cache_write_tokens * price["cache_write"]
    ) / 1_000_000


_ledger = None


def _ledger_conn():
    global _ledger
    if _ledger is None:
        _ledger = init_db(os.getenv("LEADS_DB_PATH", "leads.db"))
    return _ledger


def _record(event: dict) -> None:
    """Tracking must never break a run, so ledger failures are swallowed."""
    try:
        record_usage_event(_ledger_conn(), event)
    except Exception:  # noqa: BLE001 - sqlite/filesystem problems are not fatal here
        pass


def record_llm_call(model: str | None, input_tokens: int = 0, output_tokens: int = 0,
                    cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                    web_searches: int = 0) -> None:
    _record({
        "provider": "anthropic",
        "kind": "llm",
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cost_usd": token_cost(model, input_tokens, output_tokens,
                               cache_read_tokens, cache_write_tokens),
    })
    if web_searches:
        _record({
            "provider": "anthropic",
            "kind": "web_search",
            "model": model,
            "requests": web_searches,
            "cost_usd": web_searches * WEB_SEARCH_USD,
        })


def record_api_call(provider: str, kind: str, cost_usd: float = 0.0) -> None:
    _record({"provider": provider, "kind": kind, "cost_usd": cost_usd})


def _quota(requests_block: dict, name: str) -> dict | None:
    block = requests_block.get(name)
    if not isinstance(block, dict):
        return None
    used, available = block.get("used"), block.get("available")
    if used is None or available is None:
        return None
    return {"id": name, "label": QUOTA_LABELS.get(name, name.title()),
            "used": used, "available": available,
            "remaining": max(available - used, 0)}


def hunter_account(api_key: str | None) -> dict:
    if not api_key:
        return {"configured": False, "upgrade_url": HUNTER_UPGRADE_URL}
    try:
        resp = requests.get(HUNTER_ACCOUNT_URL, headers={"X-API-KEY": api_key}, timeout=15)
        if resp.status_code == 401:
            return {"configured": True, "error": "Hunter rejected the API key.",
                    "upgrade_url": HUNTER_UPGRADE_URL}
        resp.raise_for_status()
        data = resp.json().get("data") or {}
    except requests.RequestException as exc:
        return {"configured": True, "error": str(exc), "upgrade_url": HUNTER_UPGRADE_URL}

    quotas = [q for q in (_quota(data.get("requests") or {}, name)
                          for name in ("verifications", "searches", "credits")) if q]
    return {
        "configured": True,
        "plan_name": data.get("plan_name"),
        "plan_level": data.get("plan_level"),
        "reset_date": str(data.get("reset_date")) if data.get("reset_date") else None,
        "email": data.get("email"),
        "quotas": quotas,
        "upgrade_url": HUNTER_UPGRADE_URL,
    }


def _cost_report_pages(admin_key: str, params: dict):
    headers = {"x-api-key": admin_key, "anthropic-version": "2023-06-01"}
    for _ in range(12):
        resp = requests.get(ANTHROPIC_COST_URL, headers=headers, params=params, timeout=20)
        if resp.status_code in (401, 403):
            raise PermissionError(
                "Anthropic rejected the admin key. It must be an organisation "
                "admin key (sk-ant-admin…), not the API key the agent runs on."
            )
        resp.raise_for_status()
        body = resp.json()
        yield body
        if not body.get("has_more") or not body.get("next_page"):
            return
        params = {**params, "page": body["next_page"]}


def anthropic_cost(admin_key: str | None, starting_at: str) -> dict:
    """Billed spend per day and per model since `starting_at` (RFC 3339)."""
    if not admin_key:
        return {"configured": False, "admin_keys_url": ANTHROPIC_ADMIN_KEYS_URL}

    daily, by_model, total = [], {}, 0.0
    params = {"starting_at": starting_at, "bucket_width": "1d", "limit": 31,
              "group_by[]": "description"}
    try:
        for page in _cost_report_pages(admin_key, params):
            for bucket in page.get("data") or []:
                # Amounts come back in the currency's lowest unit (cents).
                usd = sum(float(item.get("amount") or 0) / 100
                          for item in bucket.get("results") or [])
                total += usd
                daily.append({"day": (bucket.get("starting_at") or "")[:10],
                              "cost_usd": round(usd, 4)})
                for item in bucket.get("results") or []:
                    model = item.get("model") or item.get("cost_type") or "other"
                    by_model[model] = by_model.get(model, 0.0) + float(item.get("amount") or 0) / 100
    except PermissionError as exc:
        return {"configured": True, "error": str(exc), "admin_keys_url": ANTHROPIC_ADMIN_KEYS_URL}
    except requests.RequestException as exc:
        return {"configured": True, "error": str(exc), "admin_keys_url": ANTHROPIC_ADMIN_KEYS_URL}

    return {
        "configured": True,
        "total_usd": round(total, 4),
        "daily": daily,
        "by_model": [{"model": m, "cost_usd": round(c, 4)}
                     for m, c in sorted(by_model.items(), key=lambda kv: -kv[1])],
        "usage_url": ANTHROPIC_USAGE_URL,
    }


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def summary(conn, settings: dict, hunter_key: str | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    month_start = _month_start(now).isoformat()
    window_start = (now - timedelta(days=30)).isoformat()

    # The Claude card is Anthropic-only; the by_kind breakdown covers every provider.
    estimated = {
        "month": usage_totals(conn, month_start, "anthropic"),
        "last_30_days": usage_totals(conn, window_start, "anthropic"),
        "daily": usage_grouped(conn, "day", window_start, "anthropic"),
        "by_model": usage_grouped(conn, "model", month_start, "anthropic"),
        "by_kind": usage_grouped(conn, "kind", month_start),
    }
    budget = float(settings.get("monthly_budget_usd") or 0)
    billed = anthropic_cost(settings.get("anthropic_admin_key"), month_start)
    spend_usd = billed.get("total_usd") if billed.get("total_usd") is not None \
        else estimated["month"]["cost_usd"]

    return {
        "generated_at": now.isoformat(),
        "month_start": month_start,
        "hunter": hunter_account(hunter_key),
        "anthropic": {
            "billed": billed,
            "estimated": estimated,
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            "source": "billed" if billed.get("total_usd") is not None else "estimated",
            "spend_usd": round(spend_usd or 0.0, 4),
        },
        "budget": {
            "monthly_budget_usd": budget,
            "spend_usd": round(spend_usd or 0.0, 4),
            "over_budget": bool(budget) and (spend_usd or 0) > budget,
        },
    }
