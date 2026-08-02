from state import AgentState


def route_by_intent(state: AgentState) -> str:
    """Return the branch name based on the classified intent."""
    return state["intent"]
