import json
from langchain_core.messages import SystemMessage
from state import AgentState
from constants import llm as default_llm

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant. Use web search to find real people matching "
    "the user's criteria. Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain. No prose, no markdown fences."
))


def _parse_leads(text: str) -> list:
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def find_node(state: AgentState, llm=None) -> dict:
    """Find candidate leads with Claude's web search tool."""
    model = llm or default_llm
    bound = model.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([FIND_SYSTEM, *state["messages"]])
    return {"leads": _parse_leads(response.content)}
