from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage
from state import Intent
from nodes.intent import intent_node


def test_intent_node_writes_category():
    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    state = {"messages": [HumanMessage(content="find me fintech VPs")],
             "intent": "", "leads": [], "enriched": []}
    result = intent_node(state, llm=fake_llm)

    assert result == {"intent": "find_leads"}
    fake_llm.with_structured_output.assert_called_once_with(Intent)
