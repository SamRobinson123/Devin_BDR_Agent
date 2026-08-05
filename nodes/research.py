from langchain_core.messages import HumanMessage, SystemMessage
from constants import RESEARCH_SEARCH_MAX_USES, llm as default_llm
from nodes.parsing import parse_json_object
from state import AgentState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search",
                   "max_uses": RESEARCH_SEARCH_MAX_USES}

RESEARCH_SYSTEM = SystemMessage(content=(
    "You research companies for a BDR team. Use web search on the given domain — "
    "the site itself, plus funding, hiring and news coverage — and keep searching "
    "while fields are still unverified. "
    "Return ONLY a JSON object with keys industry, employee_count, location, summary, "
    "signals. 'summary' is one sentence on what the company does. 'signals' is a short "
    "string of recent buying signals (funding, hiring, launches) or \"\" if none found. "
    "Use null for anything you cannot verify. No prose, no markdown fences."
))

RESEARCH_FIELDS = ("industry", "employee_count", "location")


def _research_domain(domain: str, company: str, llm) -> dict:
    bound = llm.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([
        RESEARCH_SYSTEM,
        HumanMessage(content=f"Company: {company or 'unknown'}\nDomain: {domain}"),
    ])
    return parse_json_object(response.content)


def _summarize(brief: dict) -> str | None:
    parts = [brief.get("summary"), brief.get("signals")]
    text = " ".join(p for p in parts if p)
    return text or None


def research_node(state: AgentState, llm=None) -> dict:
    """Attach a company brief (industry, size, location, summary) to every lead."""
    model = llm or default_llm
    leads = state.get("leads", [])

    briefs: dict[str, dict] = {}
    for lead in leads:
        domain = (lead.get("domain") or "").strip().lower()
        if domain and domain not in briefs:
            briefs[domain] = _research_domain(domain, lead.get("company"), model)

    researched = []
    for lead in leads:
        brief = briefs.get((lead.get("domain") or "").strip().lower(), {})
        extras = {f: lead.get(f) or brief.get(f) for f in RESEARCH_FIELDS}
        researched.append({**lead, **extras, "research_summary": _summarize(brief)})

    return {"leads": researched}
