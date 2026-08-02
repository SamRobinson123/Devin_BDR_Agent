from langgraph.types import interrupt
from langgraph.graph import END
from state import AgentState


def human_gate(state: AgentState) -> dict:
    """Pause and ask the human what to do with the found leads."""
    count = len(state.get("leads", []))
    decision = interrupt({
        "message": f"Found {count} leads. Reply 'enrich' to validate emails via "
                   f"Hunter, or 'done' to stop.",
        "leads": state.get("leads", []),
    })
    return {"gate_decision": decision}


def route_after_gate(state: AgentState) -> str:
    """Route to the shared enrich node or end, based on the human's reply."""
    return "enrich_node" if state.get("gate_decision") == "enrich" else END
