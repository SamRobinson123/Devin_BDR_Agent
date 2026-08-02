from state import AgentState, Intent
from constants import llm as default_llm


def intent_node(state: AgentState, llm=None) -> dict:
    """Classify the latest user message into a validated Intent."""
    model = llm or default_llm
    classifier = model.with_structured_output(Intent)
    result: Intent = classifier.invoke(state["messages"])
    return {"intent": result.category}
