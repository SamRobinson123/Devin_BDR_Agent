from typing import Annotated, Sequence, Literal
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: str
    leads: list
    enriched: list
    skipped: list
    gate_decision: str


class Intent(BaseModel):
    """Structured result of classifying the user's request."""
    category: Literal["find_leads", "enrich_leads", "clarify"] = Field(
        description="What the user is trying to do"
    )
    query: str = Field(description="Cleaned-up search criteria or target")
