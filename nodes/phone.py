import logging
import os
import re
import time
import requests
import usage
from state import AgentState

logger = logging.getLogger(__name__)

DATAGMA_SEARCH_URL = "https://gateway.datagma.net/api/ingress/v1/search"
DATAGMA_FULL_URL = "https://gateway.datagma.net/api/ingress/v2/full"
PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"

_PHONE_KEYS = ("mobile", "phone", "phone_number", "phoneNumber", "number",
               "mobile_number", "mobileNumber", "raw_number", "international")
_E164 = re.compile(r"^\+?[0-9][0-9\s().-]{6,20}$")

# Prospeo's free/low tiers rate-limit to ~1 req/s and answer a burst with 429
# ("Rate limit exceeded", and occasionally a misleading 400 INVALID_API_KEY),
# so a batch of leads would otherwise fail every lookup after the first.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 4
_BACKOFF_SECONDS = 2


def _record_lookup() -> None:
    usage.record_api_call((os.getenv("PHONE_PROVIDER") or "").strip().lower(),
                         "phone_lookup")


def _retry_delay(resp, attempt: int) -> float:
    header = getattr(resp, "headers", {}).get("Retry-After")
    try:
        return float(header)
    except (TypeError, ValueError):
        return _BACKOFF_SECONDS * (attempt + 1)


def _send(method, url: str, **kwargs):
    """Call the provider, backing off and retrying on rate limits / transient 5xx."""
    resp = None
    for attempt in range(_MAX_RETRIES + 1):
        resp = method(url, timeout=30, **kwargs)
        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            time.sleep(_retry_delay(resp, attempt))
            continue
        break
    resp.raise_for_status()
    return resp


def _billed_get(url: str, **kwargs):
    """Only a request the provider actually answered counts against the plan."""
    resp = _send(requests.get, url, **kwargs)
    _record_lookup()
    return resp


def _walk_for_phone(payload) -> str | None:
    """Providers nest phone data differently and change shape between plans;
    take the first plausible phone-looking string under a phone-ish key."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and key in _PHONE_KEYS and _E164.match(value.strip()):
                return value.strip()
            found = _walk_for_phone(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _walk_for_phone(item)
            if found:
                return found
    return None


def _datagma_lookup(lead: dict, api_key: str) -> tuple[str | None, str | None]:
    """Try every identifier we have, strongest first, so one bad match doesn't end the search."""
    linkedin, email = lead.get("linkedin_url"), lead.get("email")
    full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()

    if linkedin or email:
        params = {"apiId": api_key, "minimumMatch": 1}
        if linkedin:
            params["username"] = linkedin
        if email:
            params["email"] = email
        resp = _billed_get(DATAGMA_SEARCH_URL, params=params)
        phone = _walk_for_phone(resp.json())
        if phone:
            return phone, "high"

    if full_name and lead.get("company"):
        resp = _billed_get(DATAGMA_FULL_URL, params={
            "apiId": api_key, "fullName": full_name, "data": lead["company"],
            "phoneFull": "true",
        })
        phone = _walk_for_phone(resp.json())
        if phone:
            return phone, "medium"

    return None, None


def _prospeo_strategies(lead: dict) -> list[dict]:
    """Identifiers to try, strongest first. linkedin_url has the best hit rate,
    but if it comes up empty (stale profile, no match) the name+company-domain
    strategy gets tried instead of quitting."""
    strategies = []
    if lead.get("linkedin_url"):
        strategies.append({"linkedin_url": lead["linkedin_url"]})
    if lead.get("first_name") and lead.get("last_name") and lead.get("domain"):
        strategies.append({"first_name": lead["first_name"], "last_name": lead["last_name"],
                           "company_website": lead["domain"]})
    return strategies


def _prospeo_call(payload_data: dict, api_key: str) -> dict | None:
    """POST one strategy to Prospeo's person-enrichment endpoint.

    Requests mobile and email together so a lead's phone and email lookups
    share a single billed call instead of two. A completed response is
    deterministic for that exact payload, so unlike the 429/5xx cases
    `_send` already retries with backoff, there's no point retrying an
    empty-but-successful result here — it would just burn another credit
    for the same answer.
    """
    body = {"enrich_mobile": True, "enrich_email": True, "data": payload_data}
    resp = _send(requests.post, PROSPEO_ENRICH_URL, json=body,
                 headers={"X-KEY": api_key, "Content-Type": "application/json"})
    _record_lookup()
    return resp.json().get("person") or None


def prospeo_enrich_person(lead: dict, api_key: str) -> dict | None:
    """Run Prospeo's identifier ladder and return its full person record (mobile + email).

    Public so nodes/enrich.py can reuse it as the authoritative email source
    without spending a second Prospeo call for the same lead.
    """
    for payload_data in _prospeo_strategies(lead):
        person = _prospeo_call(payload_data, api_key)
        if person:
            return person
    return None


def _prospeo_lookup(lead: dict, api_key: str) -> tuple[str | None, str | None]:
    """Phone half of Prospeo enrichment. Reuses the person record enrich_node
    already stashed on the lead (as "_prospeo_person") when present, instead
    of making a second paid call for data we already have."""
    person = lead.get("_prospeo_person") or prospeo_enrich_person(lead, api_key)
    if not person:
        return None, None
    mobile = person.get("mobile") or {}
    if mobile.get("revealed") and mobile.get("mobile"):
        return mobile["mobile"], "high"
    phone = _walk_for_phone(person)
    return (phone, "medium") if phone else (None, None)


PROVIDERS = {
    "datagma": (_datagma_lookup, "DATAGMA_API_KEY"),
    "prospeo": (_prospeo_lookup, "PROSPEO_API_KEY"),
}


def _active_provider() -> tuple:
    """Return (lookup_fn, api_key), or (None, None) when phone lookup is off."""
    name = (os.getenv("PHONE_PROVIDER") or "none").strip().lower()
    entry = PROVIDERS.get(name)
    if not entry:
        return None, None
    lookup, key_var = entry
    api_key = os.getenv(key_var)
    return (lookup, api_key) if api_key else (None, None)


def _find_phone(lead: dict, lookup, api_key: str | None) -> dict:
    existing = (lead.get("phone") or "").strip()
    if existing and _E164.match(existing):
        return {**lead, "phone_status": "found", "phone_source": lead.get("phone_source") or "web_search",
                "phone_confidence": lead.get("phone_confidence") or "low"}
    if existing:
        lead = {**lead, "phone": None}
    if not lookup:
        return {**lead, "phone": None, "phone_status": "not_found", "phone_source": None,
                "phone_confidence": None}
    try:
        phone, confidence = lookup(lead, api_key)
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        body = getattr(exc.response, "text", None)
        logger.error(
            "Phone lookup failed for %s %s via %s (status=%s): %s",
            lead.get("first_name"), lead.get("last_name"),
            (os.getenv("PHONE_PROVIDER") or "").strip().lower(), status_code, body or exc,
        )
        return {**lead, "phone": None, "phone_status": "error", "phone_source": None,
                "phone_confidence": None}
    if not phone:
        return {**lead, "phone": None, "phone_status": "not_found", "phone_source": None,
                "phone_confidence": None}
    return {**lead, "phone": phone, "phone_status": "found",
            "phone_source": (os.getenv("PHONE_PROVIDER") or "").strip().lower(),
            "phone_confidence": confidence}


def phone_node(state: AgentState) -> dict:
    """Find a mobile number for every enriched lead via the configured provider.

    Providers are pay-per-result and charge nothing when they find nothing.
    With no PHONE_PROVIDER/API key set, this degrades to passing through whatever
    phone number find_node already saw on a page — no external calls, no cost.
    """
    lookup, api_key = _active_provider()
    enriched = [_find_phone(lead, lookup, api_key) for lead in state.get("enriched", [])]
    return {"enriched": enriched}
