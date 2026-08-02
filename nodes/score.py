import json
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from constants import llm as default_llm
from state import AgentState

SCORE_SYSTEM = SystemMessage(content=(
    "You qualify prospects for a BDR team. Score each prospect 0-100 on how well it "
    "matches the ideal customer profile in the user's request, using the company and "
    "person research provided. Weigh whether this person is plausibly the buyer — "
    "seniority and title matter as much as company fit. Give a one-sentence reason "
    "citing concrete evidence. Score 0 when the prospect clearly does not match."
))


class LeadScore(BaseModel):
    index: int = Field(description="Zero-based position of the prospect in the input list")
    score: int = Field(ge=0, le=100, description="ICP fit score")
    reason: str = Field(description="One sentence justifying the score")


class LeadScores(BaseModel):
    scores: list[LeadScore]


def _icp_text(state: AgentState) -> str:
    for message in reversed(list(state.get("messages", []))):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _prospect_payload(leads: list) -> str:
    keys = ("first_name", "last_name", "title", "company", "domain", "industry",
            "employee_count", "location", "research_summary", "seniority", "tenure",
            "person_summary", "talking_points")
    return json.dumps([{k: lead.get(k) for k in keys} for lead in leads])


def score_node(state: AgentState, llm=None) -> dict:
    """Rank prospects against the ICP in the user's request, best fit first."""
    leads = state.get("leads", [])
    if not leads:
        return {"leads": leads}

    model = llm or default_llm
    result = model.with_structured_output(LeadScores).invoke([
        SCORE_SYSTEM,
        HumanMessage(content=(
            f"Ideal customer profile: {_icp_text(state)}\n"
            f"Prospects: {_prospect_payload(leads)}"
        )),
    ])
    if not isinstance(result, LeadScores):
        return {"leads": leads}

    by_index = {s.index: s for s in result.scores}
    scored = [
        {**lead,
         "fit_score": by_index[i].score if i in by_index else None,
         "fit_reason": by_index[i].reason if i in by_index else None}
        for i, lead in enumerate(leads)
    ]
    scored.sort(key=lambda lead: lead["fit_score"] if lead["fit_score"] is not None else -1,
                reverse=True)
    return {"leads": scored}
