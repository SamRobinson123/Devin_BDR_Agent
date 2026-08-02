from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def _verifier_resp(result):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": {"result": result, "email": "jane.doe@acme.com"}}
    m.raise_for_status.return_value = None
    return m


@patch("nodes.enrich.requests.get")
def test_enrich_intent_end_to_end(mock_get):
    mock_get.return_value = _verifier_resp("deliverable")
    from graph import build_graph, Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="enrich_leads", query="Jane Doe acme.com")

    with patch("graph.llm", fake_llm):
        app = build_graph(checkpointer=MemorySaver())
        state = {
            "messages": [HumanMessage(content="enrich Jane Doe at acme.com")],
            "intent": "",
            "leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com",
                       "phone": "+1-555-0100"}],
            "enriched": [], "gate_decision": "",
        }
        final = app.invoke(state, {"configurable": {"thread_id": "t1"}})

    assert final["intent"] == "enrich_leads"
    assert final["enriched"][0]["email"] == "jane.doe@acme.com"
    assert final["enriched"][0]["status"] == "verified"
    assert final["enriched"][0]["phone"] == "+1-555-0100"
    assert final["enriched"][0]["phone_status"] == "found"
