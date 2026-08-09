import json
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def _fake_search_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = json.dumps({
        "email": "jane.doe@acme.com", "email_confidence": 92,
        "email_source": "https://acme.com/team",
        "phone": "+1-555-0100", "phone_confidence": "high",
        "phone_source": "https://acme.com/team",
    })
    llm.bind_tools.return_value.invoke.return_value = response
    return llm


def test_enrich_intent_end_to_end():
    from graph import build_graph, Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="enrich_leads", query="Jane Doe acme.com")

    with patch("graph.llm", fake_llm), patch("graph.search_llm", _fake_search_llm()):
        app = build_graph(checkpointer=MemorySaver())
        state = {
            "messages": [HumanMessage(content="enrich Jane Doe at acme.com")],
            "intent": "",
            "leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
            "enriched": [], "gate_decision": "",
        }
        final = app.invoke(state, {"configurable": {"thread_id": "t1"}})

    assert final["intent"] == "enrich_leads"
    assert final["enriched"][0]["email"] == "jane.doe@acme.com"
    assert final["enriched"][0]["status"] == "verified"
    assert final["enriched"][0]["phone"] == "+1-555-0100"
    assert final["enriched"][0]["phone_status"] == "found"
