import os
import re
import time
import requests
import usage
from state import AgentState

DATAGMA_SEARCH_URL = "https://gateway.datagma.net/api/ingress/v1/search"
DATAGMA_FULL_URL = "https://gateway.datagma.net/api/ingress/v2/full"
PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"

_PHONE_KEYS = ("mobile", "phone", "phone_number", "phoneNumber", "number",
               "mobile_number", "mobileNumber", "raw_number", "international")
_E164 = re.compile(r"^\+?[0-9][0-9\s().-]{6,20}$")


def _record_lookup() -> None:
    usage.record_api_call((os.getenv("PHONE_PROVIDER") or "").strip().lower(),
                         "phone_lookup")


def _billed_get(url: str, **kwargs):
    """Only a request the provider actually answered counts against the plan."""
    resp = requests.get(url, timeout=30, **kwargs)
    resp.raise_for_status()
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


_PROSPEO_RETRIES = 2
_PROSPEO_RETRY_DELAY_SECONDS = 3


def _prospeo_call(payload_data: dict, api_key: str) -> tuple[str | None, str | None]:
    """POST one strategy to Prospeo, retrying transient misses before giving up on it."""
    body = {"enrich_mobile": True, "data": payload_data}
    for attempt in range(_PROSPEO_RETRIES + 1):
        resp = requests.post(PROSPEO_ENRICH_URL, json=body, timeout=30,
                             headers={"X-KEY": api_key, "Content-Type": "application/json"})
        resp.raise_for_status()
        _record_lookup()
        result = resp.json()
        mobile = result.get("person", {}).get("mobile", {})
        if mobile.get("revealed") and mobile.get("mobile"):
            return mobile["mobile"], "high"
        phone = _walk_for_phone(result)
        if phone:
            return phone, "medium"
        if attempt < _PROSPEO_RETRIES:
            time.sleep(_PROSPEO_RETRY_DELAY_SECONDS)
    return None, None


def _prospeo_lookup(lead: dict, api_key: str) -> tuple[str | None, str | None]:
    """Try every identifier we have, strongest first, before reporting not_found.

    linkedin_url has the best hit rate, but if it comes up empty (stale profile,
    no match) fall back to the name+company-domain strategy instead of quitting.
    """
    strategies = []
    if lead.get("linkedin_url"):
        strategies.append({"linkedin_url": lead["linkedin_url"]})
    if lead.get("first_name") and lead.get("last_name") and lead.get("domain"):
        strategies.append({"first_name": lead["first_name"], "last_name": lead["last_name"],
                           "company_website": lead["domain"]})

    for payload_data in strategies:
        phone, confidence = _prospeo_call(payload_data, api_key)
        if phone:
            return phone, confidence
    return None, None


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
    except requests.RequestException:
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
