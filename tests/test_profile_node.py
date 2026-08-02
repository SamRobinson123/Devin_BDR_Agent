import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from nodes.profile import profile_node


def _llm(payload):
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=json.dumps(payload))
    return fake_llm, bound


def test_attaches_person_profile_to_lead():
    profile = {
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "title": "VP of Revenue Operations",
        "seniority": "vp",
        "tenure": "2 yrs 4 mo",
        "prior_companies": ["Gong"],
        "person_summary": "Owns the RevOps stack at Acme.",
        "talking_points": ["Spoke at SaaStr about CPQ migrations"],
        "profile_sources": ["https://example.com/talk"],
    }
    fake_llm, _ = _llm(profile)
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme"}]}

    lead = profile_node(state, llm=fake_llm)["leads"][0]

    assert lead["linkedin_url"] == profile["linkedin_url"]
    assert lead["seniority"] == "vp"
    assert lead["talking_points"] == profile["talking_points"]
    assert lead["first_name"] == "Jane"


def test_keeps_existing_values_over_model_output():
    fake_llm, _ = _llm({"title": "Guessed Title"})
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "title": "Known Title"}]}
    assert profile_node(state, llm=fake_llm)["leads"][0]["title"] == "Known Title"


def test_skips_leads_without_a_full_name():
    fake_llm, bound = _llm({"title": "VP"})
    state = {"leads": [{"first_name": "Jane"}]}
    result = profile_node(state, llm=fake_llm)
    bound.invoke.assert_not_called()
    assert result["leads"][0] == {"first_name": "Jane"}


def test_respects_the_per_run_lookup_budget():
    fake_llm, bound = _llm({"title": "VP"})
    state = {"leads": [{"first_name": f"P{i}", "last_name": "X"} for i in range(5)]}
    profile_node(state, llm=fake_llm, limit=2)
    assert bound.invoke.call_count == 2


def test_unparseable_response_leaves_lead_untouched():
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content="could not find anything")
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe"}]}

    lead = profile_node(state, llm=fake_llm)["leads"][0]
    assert lead["linkedin_url"] is None
    assert lead["first_name"] == "Jane"
