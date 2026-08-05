import logging
import os
import unicodedata
import requests
import usage
from nodes.concurrency import parallel_map
from nodes.phone import prospeo_enrich_person
from state import AgentState

logger = logging.getLogger(__name__)

VERIFIER_URL = "https://api.hunter.io/v2/email-verifier"
FINDER_URL = "https://api.hunter.io/v2/email-finder"

# Hunter's Email Finder bills against a separate "searches" quota from the
# verifier, and on this account that quota is a hard zero (not a rate limit
# that recovers) — every call 429s. Default it off so a normal run doesn't
# waste a round trip per lead; flip HUNTER_FINDER_ENABLED=true if the plan
# ever gets search credits.
_FINDER_ENABLED = (os.getenv("HUNTER_FINDER_ENABLED") or "").strip().lower() in ("1", "true", "yes")


def _asciify(name: str) -> str:
    """Strip accents (e.g. "Tiarnán" -> "Tiarnan") so guessed addresses are valid ASCII."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")


def _pattern_email(pattern: str, first: str, last: str, domain: str) -> str:
    f, l = first[0], last[0]
    return pattern.format(first=first, last=last, f=f, l=l) + f"@{domain}"


def _find_by_pattern(first: str, last: str, domain: str, run_cache: dict) -> str | None:
    """Ask Hunter's Email Finder for the domain's actual naming pattern.

    The finder knows a domain's real convention from emails it has on file,
    so when it's available its answer is tried before our own guesses. The
    pattern is cached per domain (scoped to this enrich_node call) so leads
    at the same company reuse it instead of each spending a separate call.
    If the account's Finder quota is exhausted (429), that's learned once
    and the rest of this run skips it instead of repeating a guaranteed miss.
    """
    if not _FINDER_ENABLED or run_cache.get("finder_dead"):
        return None

    first, last = first.lower(), last.lower()
    patterns = run_cache.setdefault("patterns", {})
    if domain in patterns:
        return _pattern_email(patterns[domain], first, last, domain)

    params = {"domain": domain, "first_name": first, "last_name": last,
              "api_key": os.getenv("HUNTER_API_KEY")}
    try:
        resp = requests.get(FINDER_URL, params=params, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 429:
            run_cache["finder_dead"] = True
            logger.warning("Hunter Email Finder is out of quota (429); skipping it for the rest of this run.")
        else:
            logger.warning("Hunter email-finder failed for %s %s @ %s: %s", first, last, domain, exc)
        return None
    usage.record_api_call("hunter", "finder")
    email = (resp.json().get("data") or {}).get("email")
    if not email:
        return None

    local = email.split("@")[0].lower()
    f, l = first[0], last[0]
    known_patterns = {
        f"{first}.{last}": "{first}.{last}",
        f"{first}{last}": "{first}{last}",
        f"{f}{last}": "{f}{last}",
        first: "{first}",
        f"{first}_{last}": "{first}_{last}",
        f"{f}.{last}": "{f}.{last}",
    }
    pattern = known_patterns.get(local)
    if pattern:
        patterns[domain] = pattern
    return email


def _guess_emails(lead: dict) -> list[str]:
    """Generate common corporate email patterns for a lead, no search API needed."""
    first = _asciify((lead.get("first_name") or "").strip().lower())
    last = _asciify((lead.get("last_name") or "").strip().lower())
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


def _prospeo_email(lead: dict) -> tuple[str | None, dict | None]:
    """Ask Prospeo for the lead's actual on-file email (not a guess).

    Prospeo enriches full people records, so its answer isn't a pattern
    guess scored for plausibility — it's the address on file for that
    specific person. Returns (email, person) so the caller can stash the
    person record for phone_node to reuse without a second paid call.
    """
    api_key = os.getenv("PROSPEO_API_KEY")
    if not api_key:
        return None, None
    try:
        person = prospeo_enrich_person(lead, api_key)
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        body = getattr(exc.response, "text", None)
        logger.warning(
            "Prospeo email lookup failed for %s %s (status=%s): %s",
            lead.get("first_name"), lead.get("last_name"), status_code, body or exc,
        )
        return None, None
    if not person:
        return None, None
    email_info = person.get("email") or {}
    if email_info.get("revealed") and email_info.get("email"):
        return email_info["email"].strip().lower(), person
    return None, person


def _find_one(lead: dict, run_cache: dict) -> dict:
    """Find a lead's email: Prospeo's on-file record first, Hunter guess+verify as fallback.

    Prospeo enrich-person returns an address it already has on file for this
    specific person, so it's authoritative when revealed — no scoring needed.
    Hunter's guess+verify ladder only kicks in when Prospeo has nothing (no
    credits, no match). On a catch-all/accept-all domain, Hunter's verifier
    accepts almost any address in the right shape — including wrong ones —
    so a bare "risky" result there is not evidence of anything and is
    reported honestly as unverifiable rather than guessed at.
    """
    prospeo_email, prospeo_person = _prospeo_email(lead)
    stash = {"_prospeo_person": prospeo_person} if prospeo_person else {}

    if prospeo_email:
        return {**lead, **stash, "email": prospeo_email, "status": "verified", "email_confidence": 100}

    first = _asciify((lead.get("first_name") or "").strip())
    last = _asciify((lead.get("last_name") or "").strip())
    domain = (lead.get("domain") or "").strip().lower()
    known_email = (lead.get("email") or "").strip().lower()
    guesses = _guess_emails(lead)

    pattern_email = _find_by_pattern(first, last, domain, run_cache) if (first and last and domain) else None
    pattern_email = pattern_email.strip().lower() if pattern_email else None

    ordered = [e for e in [pattern_email, known_email] if e] + guesses
    candidates = list(dict.fromkeys(ordered))
    if not candidates:
        return {**lead, **stash, "email": None, "status": "error", "email_confidence": None}

    failures = 0
    catch_all_domain = False
    for email in candidates:
        try:
            data = _verify_email(email)
        except requests.RequestException as exc:
            failures += 1
            status_code = getattr(exc.response, "status_code", None)
            body = getattr(exc.response, "text", None)
            logger.error(
                "Hunter verification failed for %s (lead %s %s, status=%s): %s",
                email, lead.get("first_name"), lead.get("last_name"), status_code, body or exc,
            )
            continue
        if data.get("status") == "valid":
            return {**lead, **stash, "email": email, "status": "verified", "email_confidence": data.get("score")}
        if data.get("accept_all"):
            # A catch-all domain accepts any address in the right shape —
            # including wrong ones — so the verifier can't discriminate
            # between candidates here. Further guesses would be wasted calls.
            catch_all_domain = True
            break

    if failures == len(candidates):
        return {**lead, **stash, "email": None, "status": "error", "email_confidence": None}
    if catch_all_domain:
        return {**lead, **stash, "email": None, "status": "unverifiable", "email_confidence": None}
    return {**lead, **stash, "email": None, "status": "not_found", "email_confidence": None}


def enrich_node(state: AgentState) -> dict:
    """Validate/find emails for every lead in state['leads']."""
    run_cache: dict = {}
    enriched = parallel_map(lambda lead: _find_one(lead, run_cache), state.get("leads", []))
    return {"enriched": enriched}
