from datetime import datetime, timezone

import pytest
import requests

import usage
from db import init_db, record_usage_event, usage_grouped, usage_totals


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


HUNTER_PAYLOAD = {
    "data": {
        "plan_name": "Growth",
        "plan_level": 2,
        "reset_date": "2026-06-27",
        "email": "me@co.com",
        "requests": {
            "credits": {"used": 550, "available": 10000},
            "searches": {"used": 500, "available": 10000},
            "verifications": {"used": 19000, "available": 20000},
        },
    }
}


@pytest.fixture
def conn(tmp_path):
    return init_db(str(tmp_path / "usage.db"))


def test_token_cost_prices_each_token_class_by_model(tmp_path):
    cost = usage.token_cost("claude-sonnet-4-5", input_tokens=1_000_000,
                            output_tokens=1_000_000, cache_read_tokens=1_000_000,
                            cache_write_tokens=1_000_000)
    assert cost == pytest.approx(3.0 + 15.0 + 0.3 + 3.75)


def test_unknown_model_falls_back_to_sonnet_pricing():
    assert usage.pricing_for("some-future-model") == usage.MODEL_PRICING["claude-sonnet-4"]
    assert usage.pricing_for("claude-opus-4-1")["output"] == 75.0


def test_hunter_account_normalises_quotas(monkeypatch):
    monkeypatch.setattr(usage.requests, "get", lambda *a, **k: FakeResponse(HUNTER_PAYLOAD))
    account = usage.hunter_account("key")

    assert account["plan_name"] == "Growth"
    assert account["reset_date"] == "2026-06-27"
    verifications = next(q for q in account["quotas"] if q["id"] == "verifications")
    assert verifications["remaining"] == 1000
    assert verifications["label"] == "Email verifications"
    assert account["upgrade_url"] == usage.HUNTER_UPGRADE_URL


def test_hunter_account_without_key_is_not_configured():
    assert usage.hunter_account("")["configured"] is False


def test_hunter_account_reports_a_rejected_key(monkeypatch):
    monkeypatch.setattr(usage.requests, "get",
                        lambda *a, **k: FakeResponse(status_code=401))
    account = usage.hunter_account("bad")
    assert account["configured"] is True
    assert "rejected" in account["error"]


def test_anthropic_cost_converts_cents_and_groups_by_model(monkeypatch):
    page = {
        "data": [{
            "starting_at": "2026-08-01T00:00:00Z",
            "results": [
                {"amount": "1234.5", "model": "claude-sonnet-4-5"},
                {"amount": "765.5", "model": "claude-opus-4-1"},
            ],
        }],
        "has_more": False,
    }
    monkeypatch.setattr(usage.requests, "get", lambda *a, **k: FakeResponse(page))

    report = usage.anthropic_cost("sk-ant-admin-x", "2026-08-01T00:00:00+00:00")

    assert report["total_usd"] == pytest.approx(20.0)
    assert report["daily"] == [{"day": "2026-08-01", "cost_usd": pytest.approx(20.0)}]
    assert report["by_model"][0]["model"] == "claude-sonnet-4-5"


def test_anthropic_cost_explains_a_non_admin_key(monkeypatch):
    monkeypatch.setattr(usage.requests, "get",
                        lambda *a, **k: FakeResponse(status_code=401))
    report = usage.anthropic_cost("sk-ant-api-x", "2026-08-01T00:00:00+00:00")
    assert "admin key" in report["error"]
    assert report["admin_keys_url"] == usage.ANTHROPIC_ADMIN_KEYS_URL


def test_anthropic_cost_without_admin_key_is_not_configured():
    assert usage.anthropic_cost(None, "2026-08-01T00:00:00+00:00")["configured"] is False


def test_ledger_aggregates_by_day_kind_and_model(conn):
    record_usage_event(conn, {"ts": "2026-08-01T10:00:00+00:00", "provider": "anthropic",
                              "kind": "llm", "model": "claude-sonnet-4-5",
                              "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.01})
    record_usage_event(conn, {"ts": "2026-08-02T10:00:00+00:00", "provider": "anthropic",
                              "kind": "llm", "model": "claude-sonnet-4-5",
                              "input_tokens": 2000, "output_tokens": 100, "cost_usd": 0.02})
    record_usage_event(conn, {"ts": "2026-08-02T11:00:00+00:00", "provider": "hunter",
                              "kind": "verification", "cost_usd": 0.0})

    totals = usage_totals(conn, "2026-08-01T00:00:00+00:00")
    assert totals["requests"] == 3
    assert totals["input_tokens"] == 3000
    assert totals["cost_usd"] == pytest.approx(0.03)

    days = usage_grouped(conn, "day", "2026-08-01T00:00:00+00:00")
    assert [d["day"] for d in days] == ["2026-08-01", "2026-08-02"]
    assert days[1]["requests"] == 2

    kinds = {k["kind"]: k["requests"] for k in
             usage_grouped(conn, "kind", "2026-08-01T00:00:00+00:00")}
    assert kinds == {"llm": 2, "verification": 1}

    totals_after = usage_totals(conn, "2026-08-02T00:00:00+00:00")
    assert totals_after["requests"] == 2


def test_summary_prefers_billed_spend_when_an_admin_key_works(conn, monkeypatch):
    monkeypatch.setattr(usage, "hunter_account", lambda key: {"configured": False})
    monkeypatch.setattr(usage, "anthropic_cost",
                        lambda key, start: {"configured": True, "total_usd": 12.5,
                                            "daily": [], "by_model": []})
    record_usage_event(conn, {"ts": datetime.now(timezone.utc).isoformat(),
                              "provider": "anthropic", "kind": "llm",
                              "model": "claude-sonnet-4-5", "cost_usd": 0.5})

    result = usage.summary(conn, {"anthropic_admin_key": "sk-ant-admin-x",
                                  "monthly_budget_usd": 10}, None)

    assert result["anthropic"]["source"] == "billed"
    assert result["anthropic"]["spend_usd"] == 12.5
    assert result["budget"]["over_budget"] is True


def test_summary_falls_back_to_the_local_estimate(conn, monkeypatch):
    monkeypatch.setattr(usage, "hunter_account", lambda key: {"configured": False})
    record_usage_event(conn, {"ts": datetime.now(timezone.utc).isoformat(),
                              "provider": "anthropic", "kind": "llm",
                              "model": "claude-sonnet-4-5", "cost_usd": 0.25})

    result = usage.summary(conn, {}, None)

    assert result["anthropic"]["source"] == "estimated"
    assert result["anthropic"]["spend_usd"] == pytest.approx(0.25)
    assert result["budget"]["over_budget"] is False


def test_settings_never_echo_the_admin_key_and_keep_it_when_blank():
    stored = usage.apply_update({}, {"anthropic_admin_key": "sk-ant-admin-x",
                                     "monthly_budget_usd": 25})
    assert stored["anthropic_admin_key"] == "sk-ant-admin-x"

    kept = usage.apply_update(stored, {"anthropic_admin_key": "", "monthly_budget_usd": 50})
    assert kept["anthropic_admin_key"] == "sk-ant-admin-x"
    assert kept["monthly_budget_usd"] == 50

    safe = usage.redact(kept)
    assert "anthropic_admin_key" not in safe
    assert safe["anthropic_admin_key_set"] is True
