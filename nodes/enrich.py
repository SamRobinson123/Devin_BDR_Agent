import os
import requests
from state import AgentState

HUNTER_URL = "https://api.hunter.io/v2/email-finder"


def _find_one(lead: dict) -> dict:
    """Look up a single lead's email via Hunter, return lead + email + status."""
    params = {
        "domain": lead.get("domain"),
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "api_key": os.getenv("HUNTER_API_KEY"),
    }
    try:
        resp = requests.get(HUNTER_URL, params=params, timeout=20)
        if resp.status_code != 200:
            return {**lead, "email": None, "status": "error"}
        email = (resp.json().get("data") or {}).get("email")
        status = "verified" if email else "not_found"
        return {**lead, "email": email, "status": status}
    except requests.RequestException:
        return {**lead, "email": None, "status": "error"}


def enrich_node(state: AgentState) -> dict:
    """Validate/find emails for every lead in state['leads'] via Hunter."""
    enriched = [_find_one(lead) for lead in state.get("leads", [])]
    return {"enriched": enriched}
