import json
import re


def extract_text(content) -> str:
    """Web-search responses interleave tool-use blocks with text blocks; keep the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    return text


def parse_json_object(content) -> dict:
    text = _strip_fences(extract_text(content))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
