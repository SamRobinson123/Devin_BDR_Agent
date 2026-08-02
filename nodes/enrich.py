import os
import requests
from state import AgentState

VERIFIER_URL = "https://api.hunter.io/v2/email-verifier"

# Deliverable results per Hunter's verifier: https://hunter.io/api-documentation/v2#email-verifier
_DELIVERABLE = {"deliverable"}
_RISKY_BUT_OK = {"risky"}  # accept-all/catch-all domains often score "risky" for a valid address


def _guess_emails(lead: dict) -> list[str]:
    """Generate common corporate email patterns for a lead, no search API needed."""
    first = (lead.get("first_name") or "").strip().lower()
    last = (lead.get("last_name") or "").strip().lower()
    domain = (lead.get("domain") or "").strip().lower()
    if not (first and last and domain):
        return []
    f, l = first[0], last[0]
    return [
        f"{first}.{last}@{domain}",
        f"{first}{last}@{domain}",
        f"{f}{last}@{domain}",
        f"{first}@{domain}",
        f"{first}_{last}@{domain}",
        f"{f}.{last}@{domain}",
    ]


def _verify_email(email: str) -> dict:
    """Call Hunter's email-verifier on one guessed address."""
    params = {"email": email, "api_key": os.getenv("HUNTER_API_KEY")}
    resp = requests.get(VERIFIER_URL, params=params, timeout=20)
    resp.raise_for_status()
    return (resp.json().get("data") or {})


def _find_one(lead: dict) -> dict:
    """Verify a lead's known email directly, or guess-and-verify if none is known."""
    known_email = lead.get("email")
    candidates = [known_email] if known_email else _guess_emails(lead)
    if not candidates:
        return {**lead, "email": None, "status": "error"}

    best_risky = None
    try:
        for email in candidates:
            data = _verify_email(email)
            result = data.get("result")
            if result in _DELIVERABLE:
                return {**lead, "email": email, "status": "verified"}
            if result in _RISKY_BUT_OK and best_risky is None:
                best_risky = email
        if best_risky:
            return {**lead, "email": best_risky, "status": "verified"}
        return {**lead, "email": None, "status": "not_found"}
    except requests.RequestException:
        return {**lead, "email": None, "status": "error"}


def enrich_node(state: AgentState) -> dict:
    """Validate/find emails for every lead in state['leads'] via Hunter."""
    enriched = [_find_one(lead) for lead in state.get("leads", [])]
    return {"enriched": enriched}
