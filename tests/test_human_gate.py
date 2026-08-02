from unittest.mock import patch
from nodes.human_gate import human_gate, route_after_gate


@patch("nodes.human_gate.interrupt")
def test_human_gate_stores_decision(mock_interrupt):
    mock_interrupt.return_value = "enrich"
    state = {"leads": [{"first_name": "Jane"}], "intent": "find_leads",
             "messages": [], "enriched": [], "gate_decision": ""}
    result = human_gate(state)
    assert result == {"gate_decision": "enrich"}
    mock_interrupt.assert_called_once()


def test_route_after_gate_enrich():
    assert route_after_gate({"gate_decision": "enrich"}) == "enrich_node"


def test_route_after_gate_done():
    assert route_after_gate({"gate_decision": "done"}) == "__end__"
