from langchain_core.messages import HumanMessage, SystemMessage
from constants import search_llm as default_search_llm
from nodes.concurrency import parallel_map
from nodes.parsing import parse_json_object
from state import AgentState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
WEB_FETCH_TOOL = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 8}

ENRICH_SYSTEM = SystemMessage(content=(
    "You find direct contact details for property managers on the public web for "
    "Flex's BDR team. Property managers list their email and phone publicly — on "
    "their company's contact/team/about/staff pages, rental listings, Google "
    "Business profiles, and state license directories. Use web search to locate "
    "those pages, then web fetch to open the most promising ones and extract the "
    "person's DIRECT email and phone from the actual page content. Prefer a direct "
    "line or mobile over a main office number, but a main office number is still "
    "worth returning (mark it low confidence). Only return an email or phone you "
    "actually saw on a fetched page or in a search result — NEVER guess or "
    "construct one from a name pattern.\n"
    "Return ONLY a JSON object with keys:\n"
    "- email: the address as seen, or null\n"
    "- email_confidence: 0-100 — 90+ only when the page explicitly ties the "
    "address to this person; lower for a shared inbox (info@, office@)\n"
    "- email_source: URL of the page where you saw it, or null\n"
    "- phone: the number as seen, or null\n"
    "- phone_confidence: one of high (direct/mobile tied to the person), medium "
    "(department line), low (main office number), or null\n"
    "- phone_source: URL of the page where you saw it, or null\n"
    "No prose, no markdown fences."
))


def _contact_payload(lead: dict) -> str:
    known = []
    if lead.get("email"):
        known.append(f"Possible email seen earlier: {lead['email']} (re-verify it)")
    if lead.get("phone"):
        known.append(f"Possible phone seen earlier: {lead['phone']} (re-verify it)")
    if lead.get("linkedin_url"):
        known.append(f"LinkedIn: {lead['linkedin_url']}")
    return "\n".join([
        f"Name: {lead.get('first_name')} {lead.get('last_name')}",
        f"Title: {lead.get('title') or 'unknown'}",
        f"Company: {lead.get('company') or 'unknown'}",
        f"Company website: {lead.get('domain') or 'unknown'}",
        *known,
    ])


def _find_one(lead: dict, llm) -> dict:
    """Extract one lead's public email + phone from real web pages."""
    bound = llm.bind_tools([WEB_SEARCH_TOOL, WEB_FETCH_TOOL])
    try:
        response = bound.invoke([ENRICH_SYSTEM, HumanMessage(content=_contact_payload(lead))])
        found = parse_json_object(response.content)
    except Exception:  # noqa: BLE001 - one bad lead must not sink the batch
        return {**lead, "email": None, "status": "error", "email_confidence": None,
                "phone": None, "phone_status": "error", "phone_source": None,
                "phone_confidence": None}

    email = (found.get("email") or "").strip().lower() or None
    phone = (found.get("phone") or "").strip() or None
    return {
        **lead,
        "email": email,
        "status": "verified" if email else "not_found",
        "email_confidence": found.get("email_confidence") if email else None,
        "email_source": found.get("email_source") if email else None,
        "phone": phone,
        "phone_status": "found" if phone else "not_found",
        "phone_source": found.get("phone_source") if phone else None,
        "phone_confidence": found.get("phone_confidence") if phone else None,
    }


def enrich_node(state: AgentState, llm=None) -> dict:
    """Find each lead's public email and phone with web search + web fetch."""
    model = llm or default_search_llm
    enriched = parallel_map(lambda lead: _find_one(lead, model), state.get("leads", []))
    return {"enriched": enriched}
