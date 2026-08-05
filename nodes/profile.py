from langchain_core.messages import HumanMessage, SystemMessage
from constants import PROFILE_LEAD_LIMIT, PROFILE_SEARCH_MAX_USES, llm as default_llm
from nodes.parsing import parse_json_object
from nodes.concurrency import parallel_map
from state import AgentState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search",
                   "max_uses": PROFILE_SEARCH_MAX_USES}

PROFILE_SYSTEM = SystemMessage(content=(
    "You research individual people for a BDR team. Use web search to find this "
    "person's public professional footprint — their LinkedIn profile, conference "
    "talks, podcast appearances, blog posts, press quotes, job change announcements. "
    "Run several distinct searches (name + company, name + LinkedIn, name + the "
    "topics they work on) rather than stopping at the first result page. "
    "Return ONLY a JSON object with keys linkedin_url, title, seniority, tenure, "
    "prior_companies, person_summary, talking_points, profile_sources.\n"
    "- seniority: one of c_level, vp, director, manager, ic, unknown\n"
    "- tenure: how long they have been in the current role, e.g. \"2 yrs 4 mo\"\n"
    "- prior_companies: array of company names, [] if none found\n"
    "- person_summary: one sentence on what this person actually owns\n"
    "- talking_points: array of 2-3 short, specific, verifiable hooks a rep could "
    "open a call with. Never invent one; return [] if the search found nothing.\n"
    "- profile_sources: array of URLs backing the claims above\n"
    "Use null for any field you cannot verify. Do not guess. No prose, no fences."
))

PROFILE_FIELDS = ("linkedin_url", "title", "seniority", "tenure", "prior_companies",
                  "person_summary", "talking_points", "profile_sources")


def _profile_one(lead: dict, llm) -> dict:
    bound = llm.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([
        PROFILE_SYSTEM,
        HumanMessage(content=(
            f"Name: {lead.get('first_name')} {lead.get('last_name')}\n"
            f"Company: {lead.get('company') or 'unknown'}\n"
            f"Domain: {lead.get('domain') or 'unknown'}\n"
            f"Known title: {lead.get('title') or 'unknown'}"
        )),
    ])
    return parse_json_object(response.content)


def _has_name(lead: dict) -> bool:
    return bool((lead.get("first_name") or "").strip() and (lead.get("last_name") or "").strip())


def profile_node(state: AgentState, llm=None, limit: int | None = None) -> dict:
    """Attach a person-level profile (LinkedIn, seniority, talking points) to each lead.

    One search-enabled call per lead, so only the first `limit` leads are profiled
    (default `PROFILE_LEAD_LIMIT`); dedupe_node and score_node keep that list short
    in practice.
    """
    model = llm or default_llm
    leads = state.get("leads", [])

    targets = []
    budget = PROFILE_LEAD_LIMIT if limit is None else limit
    for i, lead in enumerate(leads):
        if budget > 0 and _has_name(lead):
            budget -= 1
            targets.append(i)

    profiles = parallel_map(lambda i: _profile_one(leads[i], model), targets)
    by_index = dict(zip(targets, profiles))

    profiled = []
    for i, lead in enumerate(leads):
        profile = by_index.get(i)
        if profile is None:
            profiled.append(lead)
            continue
        merged = {f: lead.get(f) or profile.get(f) for f in PROFILE_FIELDS}
        profiled.append({**lead, **merged})

    return {"leads": profiled}
