from langchain_core.messages import HumanMessage, SystemMessage
from constants import llm as default_llm
from nodes.parsing import parse_json_object
from state import AgentState

DRAFT_SYSTEM = SystemMessage(content=(
    "You write first-touch cold emails for a BDR team. Return ONLY a JSON object with "
    "keys subject and body. Under 120 words, no fluff, one specific personalization "
    "drawn from the research, and one clear ask for a short call. No markdown fences."
))


def _draft_one(lead: dict, offer: str, llm) -> dict:
    response = llm.invoke([
        DRAFT_SYSTEM,
        HumanMessage(content=(
            f"What we sell / who we are: {offer}\n"
            f"Prospect: {lead.get('first_name')} {lead.get('last_name')}, "
            f"{lead.get('title') or 'unknown title'} at {lead.get('company')}\n"
            f"Research: {lead.get('research_summary') or 'none'}\n"
            f"Why they fit: {lead.get('fit_reason') or 'unknown'}"
        )),
    ])
    draft = parse_json_object(response.content)
    return {**lead,
            "draft_subject": draft.get("subject"),
            "draft_body": draft.get("body")}


def _offer_text(state: AgentState) -> str:
    for message in state.get("messages", []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def draft_node(state: AgentState, llm=None) -> dict:
    """Write a personalized opener for every enriched lead that has an email."""
    model = llm or default_llm
    offer = _offer_text(state)
    drafted = [
        _draft_one(lead, offer, model) if lead.get("email") else lead
        for lead in state.get("enriched", [])
    ]
    return {"enriched": drafted}
