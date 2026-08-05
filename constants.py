import os

from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv

from llm_usage import UsageRecorder

load_dotenv()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
SEARCH_MODEL = os.getenv("ANTHROPIC_SEARCH_MODEL", "claude-haiku-4-5")


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """Positive int from the environment, falling back to the default when unset/garbage."""
    raw = (os.getenv(name) or "").strip()
    try:
        return max(minimum, int(raw)) if raw else default
    except ValueError:
        return default


MAX_TOKENS = env_int("ANTHROPIC_MAX_TOKENS", 4096)

# Web-search iterations Claude may spend per node call. Higher = deeper research,
# more billed searches and latency. Read once at startup.
FIND_SEARCH_MAX_USES = env_int("FIND_SEARCH_MAX_USES", 20)
RESEARCH_SEARCH_MAX_USES = env_int("RESEARCH_SEARCH_MAX_USES", 8)
PROFILE_SEARCH_MAX_USES = env_int("PROFILE_SEARCH_MAX_USES", 10)

# How many leads profile_node researches individually (one search-enabled call each).
PROFILE_LEAD_LIMIT = env_int("PROFILE_LEAD_LIMIT", 15)

llm = ChatAnthropic(model=MODEL, temperature=0, max_tokens=MAX_TOKENS,
                    callbacks=[UsageRecorder()])
search_llm = ChatAnthropic(model=SEARCH_MODEL, temperature=0, max_tokens=MAX_TOKENS,
                           callbacks=[UsageRecorder()])
