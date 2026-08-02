import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from nodes.research import research_node


def _llm_returning(payload):
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=json.dumps(payload))
    return fake_llm, bound


def test_attaches_company_brief_to_each_lead():
    fake_llm, _ = _llm_returning({
        "industry": "Fintech", "employee_count": "200", "location": "NYC",
        "summary": "Acme does payments.", "signals": "Raised a Series B.",
    })
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe",
                        "company": "Acme", "domain": "acme.com"}]}

    lead = research_node(state, llm=fake_llm)["leads"][0]

    assert lead["industry"] == "Fintech"
    assert lead["employee_count"] == "200"
    assert lead["research_summary"] == "Acme does payments. Raised a Series B."


def test_researches_each_domain_once():
    fake_llm, bound = _llm_returning({"industry": "Fintech", "summary": "x"})
    state = {"leads": [
        {"first_name": "A", "last_name": "B", "domain": "acme.com"},
        {"first_name": "C", "last_name": "D", "domain": "acme.com"},
        {"first_name": "E", "last_name": "F", "domain": "beta.com"},
    ]}

    research_node(state, llm=fake_llm)

    assert bound.invoke.call_count == 2


def test_survives_unparseable_response():
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content="no idea")
    state = {"leads": [{"first_name": "A", "last_name": "B", "domain": "acme.com"}]}

    lead = research_node(state, llm=fake_llm)["leads"][0]

    assert lead["industry"] is None
    assert lead["research_summary"] is None
