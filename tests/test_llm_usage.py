from types import SimpleNamespace

import llm_usage
import usage


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata


def _result(message):
    return SimpleNamespace(generations=[[SimpleNamespace(message=message)]])


def test_extract_splits_cached_tokens_out_of_the_input_count():
    message = FakeMessage(
        usage_metadata={"input_tokens": 1000, "output_tokens": 200,
                        "input_token_details": {"cache_read": 600, "cache_creation": 100}},
        response_metadata={"model_name": "claude-sonnet-4-5",
                           "usage": {"server_tool_use": {"web_search_requests": 2}}},
    )
    assert llm_usage.extract(message) == {
        "model": "claude-sonnet-4-5",
        "input_tokens": 300,
        "output_tokens": 200,
        "cache_read_tokens": 600,
        "cache_write_tokens": 100,
        "web_searches": 2,
    }


def test_extract_tolerates_missing_metadata():
    counts = llm_usage.extract(FakeMessage())
    assert counts["input_tokens"] == 0
    assert counts["model"] is None


def test_recorder_records_tokens_and_web_searches(monkeypatch):
    recorded = []
    monkeypatch.setattr(usage, "_record", recorded.append)

    llm_usage.UsageRecorder().on_llm_end(_result(FakeMessage(
        usage_metadata={"input_tokens": 1000, "output_tokens": 1000},
        response_metadata={"model_name": "claude-sonnet-4-5",
                           "usage": {"server_tool_use": {"web_search_requests": 3}}},
    )))

    kinds = [event["kind"] for event in recorded]
    assert kinds == ["llm", "web_search"]
    assert recorded[0]["cost_usd"] == usage.token_cost("claude-sonnet-4-5", 1000, 1000)
    assert recorded[1]["requests"] == 3
    assert recorded[1]["cost_usd"] == 3 * usage.WEB_SEARCH_USD


def test_recorder_skips_calls_with_no_usage_metadata(monkeypatch):
    recorded = []
    monkeypatch.setattr(usage, "_record", recorded.append)
    llm_usage.UsageRecorder().on_llm_end(_result(FakeMessage()))
    assert recorded == []


def test_ledger_failures_never_bubble_up(monkeypatch):
    def explode():
        raise RuntimeError("no database")

    monkeypatch.setattr(usage, "_ledger_conn", explode)
    usage.record_api_call("hunter", "verification")
