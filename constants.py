import os

from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv

from llm_usage import UsageRecorder

load_dotenv()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
SEARCH_MODEL = os.getenv("ANTHROPIC_SEARCH_MODEL", "claude-sonnet-5")

llm = ChatAnthropic(model=MODEL, temperature=0, max_tokens=2048,
                    callbacks=[UsageRecorder()])
# web_fetch is a beta server tool; the header enables it for every search_llm call.
search_llm = ChatAnthropic(model=SEARCH_MODEL, max_tokens=2048,
                           default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
                           callbacks=[UsageRecorder()])
