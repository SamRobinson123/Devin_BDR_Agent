from langgraph.types import interrupt
from langgraph.graph import END
from state import AgentState


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


def route_after_enrich(state: AgentState) -> str:
    """Only write outreach drafts when the human explicitly asked for them."""
    return "draft_node" if state.get("gate_decision") == "draft" else END
