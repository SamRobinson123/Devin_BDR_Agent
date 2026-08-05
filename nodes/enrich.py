import logging
import os
import requests
import usage
from state import AgentState

logger = logging.getLogger(__name__)

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
    usage.record_api_call("hunter", "verification")
    return (resp.json().get("data") or {})


def _find_one(lead: dict) -> dict:
    """Verify a lead's known email through Hunter, then fall back to guessed patterns.

    A "known" email may just be an unverified guess scraped off a search result
    (e.g. ZoomInfo/RocketReach), so it's checked first but not trusted on its own —
    the pattern guesses still run if it isn't confirmed deliverable/risky.
    """
    known_email = (lead.get("email") or "").strip().lower()
    guesses = _guess_emails(lead)
    candidates = [known_email] + [g for g in guesses if g != known_email] if known_email else guesses
    if not candidates:
        return {**lead, "email": None, "status": "error", "email_confidence": None}

    best_risky = None
    try:
        for email in candidates:
            data = _verify_email(email)
            result = data.get("result")
            if result in _DELIVERABLE:
                return {**lead, "email": email, "status": "verified",
                        "email_confidence": data.get("score")}
            if result in _RISKY_BUT_OK and best_risky is None:
                best_risky = (email, data.get("score"))
        if best_risky:
            email, score = best_risky
            return {**lead, "email": email, "status": "verified", "email_confidence": score}
        return {**lead, "email": None, "status": "not_found", "email_confidence": None}
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        body = getattr(exc.response, "text", None)
        logger.error(
            "Hunter verification failed for lead %s %s (status=%s): %s",
            lead.get("first_name"), lead.get("last_name"), status_code, body or exc,
        )
        return {**lead, "email": None, "status": "error", "email_confidence": None}


def enrich_node(state: AgentState) -> dict:
    """Validate/find emails for every lead in state['leads'] via Hunter."""
    enriched = [_find_one(lead) for lead in state.get("leads", [])]
    return {"enriched": enriched}
