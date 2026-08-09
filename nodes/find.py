from langchain_core.messages import SystemMessage
from constants import llm as default_llm
from nodes.parsing import parse_json_array
from state import AgentState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 10}
WEB_FETCH_TOOL = {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 5}

FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant for Flex, which sells to property management "
    "companies that use AppFolio. Use web search to find real people matching the "
    "user's criteria at property management firms. Prioritize people who actually "
    "manage properties day-to-day: titles like Property Manager, Senior/Regional "
    "Property Manager, Portfolio Manager, Director of Property Management, or VP of "
    "Property Management. A company without a findable property manager is not a "
    "valid lead — skip it rather than substituting owners, brokers, or admin staff. "
    "Prefer firms showing AppFolio usage (rental listings hosted on *.appfolio.com, "
    "an AppFolio tenant/owner portal link on their site, or job posts mentioning "
    "AppFolio). Once you identify a person, use web fetch to open their "
    "company's contact/team/about page and read it for a direct phone number or "
    "email before giving up. "
    "If the user named a specific person and you cannot confirm that exact person "
    "exists at that company, return an empty JSON array — do NOT substitute other "
    "people at the company as if they matched the request. "
    "Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain, and — only if visible in your search "
    "results — email and phone. Omit email/phone entirely if not directly found; "
    "never guess them. No prose, no markdown fences."
))


def find_node(state: AgentState, llm=None) -> dict:
    """Find candidate leads with Claude's web search tool."""
    model = llm or default_llm
    bound = model.bind_tools([WEB_SEARCH_TOOL, WEB_FETCH_TOOL])
    response = bound.invoke([FIND_SYSTEM, *state["messages"]])
    return {"leads": parse_json_array(response.content)}
