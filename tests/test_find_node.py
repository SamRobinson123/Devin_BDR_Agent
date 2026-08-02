import json
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage
from nodes.find import find_node


def test_find_node_parses_leads():
    leads = [{"first_name": "Jane", "last_name": "Doe",
              "company": "Acme", "domain": "acme.com"}]
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=json.dumps(leads))

    state = {"messages": [HumanMessage(content="find fintech VPs")],
             "intent": "find_leads", "leads": [], "enriched": []}
    result = find_node(state, llm=fake_llm)

    assert result["leads"] == leads
    fake_llm.bind_tools.assert_called_once()


def test_find_node_returns_empty_on_bad_json():
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content="sorry, no results")

    state = {"messages": [HumanMessage(content="find nobody")],
             "intent": "find_leads", "leads": [], "enriched": []}
    result = find_node(state, llm=fake_llm)
    assert result["leads"] == []
