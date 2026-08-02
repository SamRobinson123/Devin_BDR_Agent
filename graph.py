import os
import re
import sys
import json
import sqlite3
import requests
from typing import Annotated, Sequence, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

from constants import llm
from nodes.dedupe import dedupe_node
from nodes.research import research_node
from nodes.score import score_node
from nodes.draft import draft_node

AGENT_DB_PATH = os.getenv("AGENT_DB_PATH", "agent.db")


# ------------------------------------------------------------------------------------------
# STATE
# ------------------------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: str
    leads: list
    enriched: list
    skipped: list
    gate_decision: str


class Intent(BaseModel):
    category: Literal["find_leads", "enrich_leads", "clarify"] = Field(
        description="What the user is trying to do"
    )
    query: str = Field(description="Cleaned-up search criteria or target")


# ------------------------------------------------------------------------------------------
# INTENT NODE + ROUTER
# ------------------------------------------------------------------------------------------

def intent_node(state: AgentState) -> dict:
    """Classify the latest user message into a validated Intent."""
    classifier = llm.with_structured_output(Intent)
    result: Intent = classifier.invoke(state["messages"])
    return {"intent": result.category}


def route_by_intent(state: AgentState) -> str:
    """Return the branch name based on the classified intent."""
    return state["intent"]


# ------------------------------------------------------------------------------------------
# FIND NODE (web search)
# ------------------------------------------------------------------------------------------

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant. Use web search to find real people matching "
    "the user's criteria. Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain, and — only if visible in your search "
    "results — email and phone. Omit email/phone entirely if not directly found; "
    "never guess them. No prose, no markdown fences."
))


def _extract_text(content) -> str:
    """Content may be a plain string or a list of content blocks (web search
    responses include server_tool_use/web_search_tool_result blocks alongside
    the model's final text block) — pull out just the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _parse_leads(content) -> list:
    text = _extract_text(content).strip()
    # Strip markdown code fences if the model wrapped the JSON anyway.
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def find_node(state: AgentState) -> dict:
    """Find candidate leads with Claude's web search tool."""
    bound = llm.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([FIND_SYSTEM, *state["messages"]])
    return {"leads": _parse_leads(response.content)}


# ------------------------------------------------------------------------------------------
# ENRICH NODE (Hunter)
# ------------------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------------------
# APOLLO PHONE NODE
# ------------------------------------------------------------------------------------------
# Apollo's people/match endpoint is paywalled off the Free plan (403 API_INACCESSIBLE),
# and every phone-lookup provider we evaluated has no usable free tier either — see
# docs/superpowers/specs/2026-08-01-phone-email-enrichment-design.md. So this node makes
# no external calls: it only surfaces a phone number when find_node's web search already
# found one on the page it read.


def _find_phone(lead: dict) -> dict:
    """Pass through a phone number if web search already found one; no API lookup."""
    if lead.get("phone"):
        return {**lead, "phone": lead["phone"], "phone_status": "found"}
    return {**lead, "phone": None, "phone_status": "not_found"}


def apollo_phone_node(state: AgentState) -> dict:
    """Surface phone numbers already found by find_node for every lead in state['enriched']."""
    enriched = [_find_phone(lead) for lead in state.get("enriched", [])]
    return {"enriched": enriched}


# ------------------------------------------------------------------------------------------
# HUMAN GATE (interrupt)
# ------------------------------------------------------------------------------------------

def human_gate(state: AgentState) -> dict:
    """Pause and ask the human what to do with the qualified leads."""
    count = len(state.get("leads", []))
    skipped = len(state.get("skipped", []))
    already = f" ({skipped} already in your database, skipped)" if skipped else ""
    decision = interrupt({
        "message": f"Found {count} new leads{already}, ranked by ICP fit. Reply "
                   f"'enrich' to validate emails and phone numbers, 'draft' to also "
                   f"write personalized openers, or 'done' to stop.",
        "leads": state.get("leads", []),
    })
    return {"gate_decision": decision}


def route_after_gate(state: AgentState) -> str:
    """Route to the shared enrich node or end, based on the human's reply."""
    return "enrich_node" if state.get("gate_decision") in ("enrich", "draft") else END


def route_after_phone(state: AgentState) -> str:
    """Only write outreach drafts when the human explicitly asked for them."""
    return "draft_node" if state.get("gate_decision") == "draft" else END


# ------------------------------------------------------------------------------------------
# BUILD + COMPILE THE GRAPH
# ------------------------------------------------------------------------------------------

def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intent_node", intent_node)
    g.add_node("find_node", find_node)
    g.add_node("dedupe_node", dedupe_node)
    g.add_node("research_node", lambda state: research_node(state, llm=llm))
    g.add_node("score_node", lambda state: score_node(state, llm=llm))
    g.add_node("human_gate", human_gate)
    g.add_node("enrich_node", enrich_node)
    g.add_node("apollo_phone_node", apollo_phone_node)
    g.add_node("draft_node", lambda state: draft_node(state, llm=llm))

    g.add_edge(START, "intent_node")
    g.add_conditional_edges("intent_node", route_by_intent, {
        "find_leads": "find_node",
        "enrich_leads": "enrich_node",
        "clarify": END,
    })
    g.add_edge("find_node", "dedupe_node")
    g.add_edge("dedupe_node", "research_node")
    g.add_edge("research_node", "score_node")
    g.add_edge("score_node", "human_gate")
    g.add_conditional_edges("human_gate", route_after_gate, {
        "enrich_node": "enrich_node",
        END: END,
    })
    g.add_edge("enrich_node", "apollo_phone_node")
    g.add_conditional_edges("apollo_phone_node", route_after_phone, {
        "draft_node": "draft_node",
        END: END,
    })
    g.add_edge("draft_node", END)

    if checkpointer is None:
        conn = sqlite3.connect(AGENT_DB_PATH, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        checkpointer.setup()

    return g.compile(checkpointer=checkpointer)


app = build_graph()


if __name__ == "__main__":
    from langgraph.types import Command

    text = sys.argv[1] if len(sys.argv) > 1 else "Find VPs of Sales at fintech startups"
    config = {"configurable": {"thread_id": "demo-1"}}
    final = app.invoke(
        {"messages": [HumanMessage(content=text)],
         "intent": "", "leads": [], "enriched": [], "skipped": [], "gate_decision": ""},
        config,
    )

    while "__interrupt__" in final:
        payload = final["__interrupt__"][0].value
        print(payload["message"])
        for lead in payload["leads"]:
            print(" -", lead)
        reply = input("enrich / draft / done > ").strip().lower()
        final = app.invoke(Command(resume=reply), config)

    print("intent  :", final.get("intent"))
    print("leads   :", final.get("leads"))
    print("enriched:", final.get("enriched"))
