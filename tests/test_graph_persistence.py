import os
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage


def test_state_persists_across_two_build_graph_calls(tmp_path):
    db_path = str(tmp_path / "test_agent.db")
    with patch.dict(os.environ, {"AGENT_DB_PATH": db_path}):
        import importlib
        import graph
        importlib.reload(graph)

        fake_llm = MagicMock()
        structured = MagicMock()
        fake_llm.with_structured_output.return_value = structured
        from graph import Intent
        structured.invoke.return_value = Intent(category="clarify", query="")

        with patch("graph.llm", fake_llm):
            app1 = graph.build_graph()
            config = {"configurable": {"thread_id": "persist-1"}}
            app1.invoke(
                {"messages": [HumanMessage(content="hello")], "intent": "",
                 "leads": [], "enriched": [], "gate_decision": ""},
                config,
            )

            app2 = graph.build_graph()
            state = app2.get_state(config)
            assert state.values["intent"] == "clarify"
