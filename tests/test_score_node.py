from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage
from nodes.score import score_node, LeadScore, LeadScores


def _llm_returning(result):
    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = result
    return fake_llm


def test_scores_and_sorts_best_fit_first():
    fake_llm = _llm_returning(LeadScores(scores=[
        LeadScore(index=0, score=20, reason="Wrong industry"),
        LeadScore(index=1, score=90, reason="Fintech VP, right size"),
    ]))
    state = {
        "messages": [HumanMessage(content="VPs of Sales at fintech startups")],
        "leads": [{"first_name": "Low", "last_name": "Fit", "domain": "a.com"},
                  {"first_name": "High", "last_name": "Fit", "domain": "b.com"}],
    }

    leads = score_node(state, llm=fake_llm)["leads"]

    assert [lead["first_name"] for lead in leads] == ["High", "Low"]
    assert leads[0]["fit_score"] == 90
    assert leads[0]["fit_reason"] == "Fintech VP, right size"


def test_no_llm_call_without_leads():
    fake_llm = _llm_returning(LeadScores(scores=[]))
    assert score_node({"messages": [], "leads": []}, llm=fake_llm)["leads"] == []
    fake_llm.with_structured_output.assert_not_called()


def test_leaves_leads_untouched_on_unexpected_result():
    fake_llm = _llm_returning("not a LeadScores")
    leads = [{"first_name": "Jane", "last_name": "Doe", "domain": "a.com"}]

    assert score_node({"messages": [], "leads": leads}, llm=fake_llm)["leads"] == leads
