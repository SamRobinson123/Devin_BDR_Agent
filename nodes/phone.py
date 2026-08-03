import os
import re
import requests
import usage
from state import AgentState

DATAGMA_SEARCH_URL = "https://gateway.datagma.net/api/ingress/v1/search"
DATAGMA_FULL_URL = "https://gateway.datagma.net/api/ingress/v2/full"
PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich"

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


def _datagma_lookup(lead: dict, api_key: str) -> str | None:
    linkedin, email = lead.get("linkedin_url"), lead.get("email")
    if linkedin or email:
        params = {"apiId": api_key, "minimumMatch": 1}
        if linkedin:
            params["username"] = linkedin
        if email:
            params["email"] = email
        resp = _billed_get(DATAGMA_SEARCH_URL, params=params)
    else:
        full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
        if not (full_name and lead.get("company")):
            return None
        resp = _billed_get(DATAGMA_FULL_URL, params={
            "apiId": api_key, "fullName": full_name, "data": lead["company"],
            "phoneFull": "true",
        })
    return _walk_for_phone(resp.json())


def _prospeo_lookup(lead: dict, api_key: str) -> str | None:
    body = {"reveal_phone_number": True}
    if lead.get("linkedin_url"):
        body["linkedin_url"] = lead["linkedin_url"]
    elif lead.get("first_name") and lead.get("last_name") and lead.get("domain"):
        body.update({"first_name": lead["first_name"], "last_name": lead["last_name"],
                     "company_domain": lead["domain"]})
    else:
        return None
    resp = requests.post(PROSPEO_ENRICH_URL, json=body, timeout=30,
                         headers={"X-KEY": api_key, "Content-Type": "application/json"})
    resp.raise_for_status()
    _record_lookup()
    return _walk_for_phone(resp.json())


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
    if lead.get("phone"):
        return {**lead, "phone_status": "found", "phone_source": lead.get("phone_source") or "web_search"}
    if not lookup:
        return {**lead, "phone": None, "phone_status": "not_found", "phone_source": None}
    try:
        phone = lookup(lead, api_key)
    except requests.RequestException:
        return {**lead, "phone": None, "phone_status": "error", "phone_source": None}
    if not phone:
        return {**lead, "phone": None, "phone_status": "not_found", "phone_source": None}
    return {**lead, "phone": phone, "phone_status": "found",
            "phone_source": (os.getenv("PHONE_PROVIDER") or "").strip().lower()}


def phone_node(state: AgentState) -> dict:
    """Find a mobile number for every enriched lead via the configured provider.

    Providers are pay-per-result and charge nothing when they find nothing.
    With no PHONE_PROVIDER/API key set, this degrades to passing through whatever
    phone number find_node already saw on a page — no external calls, no cost.
    """
    lookup, api_key = _active_provider()
    enriched = [_find_phone(lead, lookup, api_key) for lead in state.get("enriched", [])]
    return {"enriched": enriched}
