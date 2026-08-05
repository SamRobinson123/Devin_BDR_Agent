from langchain_core.messages import SystemMessage
from constants import FIND_SEARCH_MAX_USES, llm as default_llm
from nodes.parsing import parse_json_array
from state import AgentState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search",
                   "max_uses": FIND_SEARCH_MAX_USES}

FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant. Use web search to find real people matching "
    "the user's criteria. Search broadly: vary your queries (role synonyms, "
    "job-title pages, news, directories) and keep searching until you have "
    "exhausted your search budget or run out of new candidates. "
    "Once you identify a person, check their company's "
    "contact/team/about page for a direct phone number or email before giving up. "
    "Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain, and — only if visible in your search "
    "results — email and phone. Omit email/phone entirely if not directly found; "
    "never guess them. No prose, no markdown fences."
))


def find_node(state: AgentState, llm=None) -> dict:
    """Find candidate leads with Claude's web search tool."""
    model = llm or default_llm
    bound = model.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([FIND_SYSTEM, *state["messages"]])
    return {"leads": parse_json_array(response.content)}
