import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage

import constants
from nodes import find, profile, research
from nodes.profile import profile_node


def test_env_int_handles_unset_blank_and_garbage(monkeypatch):
    monkeypatch.delenv("SEARCH_DEPTH_PROBE", raising=False)
    assert constants.env_int("SEARCH_DEPTH_PROBE", 7) == 7
    monkeypatch.setenv("SEARCH_DEPTH_PROBE", "  ")
    assert constants.env_int("SEARCH_DEPTH_PROBE", 7) == 7
    monkeypatch.setenv("SEARCH_DEPTH_PROBE", "not-a-number")
    assert constants.env_int("SEARCH_DEPTH_PROBE", 7) == 7
    monkeypatch.setenv("SEARCH_DEPTH_PROBE", "0")
    assert constants.env_int("SEARCH_DEPTH_PROBE", 7) == 1
    monkeypatch.setenv("SEARCH_DEPTH_PROBE", "25")
    assert constants.env_int("SEARCH_DEPTH_PROBE", 7) == 25


def test_search_budgets_come_from_config():
    assert find.WEB_SEARCH_TOOL["max_uses"] == constants.FIND_SEARCH_MAX_USES
    assert research.WEB_SEARCH_TOOL["max_uses"] == constants.RESEARCH_SEARCH_MAX_USES
    assert profile.WEB_SEARCH_TOOL["max_uses"] == constants.PROFILE_SEARCH_MAX_USES


def test_profile_node_default_limit_follows_config(monkeypatch):
    fake_llm = MagicMock()
    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=json.dumps({"title": "VP"}))
    monkeypatch.setattr(profile, "PROFILE_LEAD_LIMIT", 3)
    leads = [{"first_name": f"A{i}", "last_name": "B"} for i in range(5)]

    profile_node({"leads": leads}, llm=fake_llm)

    assert bound.invoke.call_count == 3
