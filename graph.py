import os
import sys
import sqlite3

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from constants import llm, search_llm
from routing import route_by_intent
from state import AgentState, Intent  # noqa: F401  (re-exported for callers)
from nodes.intent import intent_node
from nodes.find import find_node
from nodes.dedupe import dedupe_node
from nodes.research import research_node
from nodes.profile import profile_node
from nodes.score import score_node
from nodes.human_gate import human_gate, route_after_gate, route_after_phone
from nodes.enrich import enrich_node
from nodes.phone import phone_node
from nodes.draft import draft_node
from nodes.notify import notify_node

AGENT_DB_PATH = os.getenv("AGENT_DB_PATH", "agent.db")


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intent_node", lambda state: intent_node(state, llm=llm))
    g.add_node("find_node", lambda state: find_node(state, llm=search_llm))
    g.add_node("dedupe_node", dedupe_node)
    g.add_node("research_node", lambda state: research_node(state, llm=search_llm))
    g.add_node("profile_node", lambda state: profile_node(state, llm=search_llm))
    g.add_node("score_node", lambda state: score_node(state, llm=llm))
    g.add_node("human_gate", human_gate)
    g.add_node("enrich_node", enrich_node)
    g.add_node("phone_node", phone_node)
    g.add_node("draft_node", lambda state: draft_node(state, llm=llm))
    g.add_node("notify_node", notify_node)

    g.add_edge(START, "intent_node")
    g.add_conditional_edges("intent_node", route_by_intent, {
        "find_leads": "find_node",
        "enrich_leads": "enrich_node",
        "clarify": END,
    })
    g.add_edge("find_node", "dedupe_node")
    g.add_edge("dedupe_node", "research_node")
    g.add_edge("research_node", "profile_node")
    g.add_edge("profile_node", "score_node")
    g.add_edge("score_node", "human_gate")
    g.add_conditional_edges("human_gate", route_after_gate, {
        "enrich_node": "enrich_node",
        END: END,
    })
    g.add_edge("enrich_node", "phone_node")
    g.add_conditional_edges("phone_node", route_after_phone, {
        "draft_node": "draft_node",
        END: "notify_node",
    })
    g.add_edge("draft_node", "notify_node")
    g.add_edge("notify_node", END)

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
