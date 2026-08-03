"""Records every Claude call into the usage ledger so the Usage tab can price it."""

from langchain_core.callbacks import BaseCallbackHandler

import usage


def extract(message) -> dict:
    """Pull token counts out of an AIMessage, tolerating missing metadata."""
    meta = getattr(message, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    response_meta = getattr(message, "response_metadata", None) or {}
    server_tools = (response_meta.get("usage") or {}).get("server_tool_use") or {}
    cache_read = details.get("cache_read", 0) or 0
    cache_write = details.get("cache_creation", 0) or 0
    return {
        "model": response_meta.get("model_name") or response_meta.get("model"),
        # usage_metadata.input_tokens already includes the cached portions.
        "input_tokens": max((meta.get("input_tokens") or 0) - cache_read - cache_write, 0),
        "output_tokens": meta.get("output_tokens") or 0,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "web_searches": server_tools.get("web_search_requests") or 0,
    }


class UsageRecorder(BaseCallbackHandler):
    def on_llm_end(self, response, **kwargs) -> None:
        for generation in getattr(response, "generations", []) or []:
            for item in generation:
                message = getattr(item, "message", None)
                if message is None:
                    continue
                counts = extract(message)
                if any(v for k, v in counts.items() if k != "model"):
                    usage.record_llm_call(**counts)
