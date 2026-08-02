import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage
from nodes.draft import draft_node


def _llm_returning(payload):
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content=json.dumps(payload))
    return fake_llm


def test_writes_a_draft_for_leads_with_an_email():
    fake_llm = _llm_returning({"subject": "Quick question, Jane",
                               "body": "Saw the Series B..."})
    state = {
        "messages": [HumanMessage(content="find fintech VPs")],
        "enriched": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme",
                      "email": "jane@acme.com", "research_summary": "Raised a Series B."}],
    }

    lead = draft_node(state, llm=fake_llm)["enriched"][0]

    assert lead["draft_subject"] == "Quick question, Jane"
    assert lead["draft_body"] == "Saw the Series B..."


def test_skips_leads_without_an_email():
    fake_llm = _llm_returning({"subject": "s", "body": "b"})
    state = {"messages": [], "enriched": [
        {"first_name": "No", "last_name": "Email", "email": None},
    ]}

    lead = draft_node(state, llm=fake_llm)["enriched"][0]

    assert "draft_subject" not in lead
    fake_llm.invoke.assert_not_called()
