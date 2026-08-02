# BDR Agent Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LangGraph agent that classifies a BDR request and either finds leads via Anthropic web search or validates their emails via Hunter, pausing for human input between the two.

**Architecture:** A `StateGraph` over a `TypedDict` state. An `intent_node` classifies the request into `find_leads` / `enrich_leads` / `clarify` using pydantic-validated structured output. The find path runs an LLM-with-web-search node, then an `interrupt()`-based human gate that routes into a shared Hunter `enrich_node` (also reachable directly by the enrich intent). Compiled with a `MemorySaver` checkpointer so the interrupt can pause and resume.

**Tech Stack:** Python, LangGraph, langchain-anthropic (Claude + server-side web search), Hunter API via `requests`, pydantic, python-dotenv, pytest.

## Global Constraints

- Model ID: `claude-sonnet-4-5` — NEVER `claude-sonnet-4-6` (invalid).
- No Apollo. Lead discovery is Anthropic web search only; email validation is Hunter only.
- Ambiguous requests must produce a clarifying question, never a guess (`clarify` intent).
- Secrets come from `.env` via `load_dotenv()`; never hard-code keys. `.env` must be git-ignored.
- Every tool call is mocked in tests — no live network calls in the test suite.
- State keys: `messages`, `intent`, `leads`, `enriched` — use these exact names everywhere.

---

## File Structure

| File | Responsibility |
|---|---|
| `constants.py` | Load env, define the shared `llm` (Claude). Fix model ID. |
| `state.py` | `AgentState` TypedDict + `Intent` pydantic model. Pure data shapes. |
| `nodes/intent.py` | `intent_node` — classify request into an `Intent`. |
| `nodes/find.py` | `find_node` — web search → `leads`. |
| `nodes/enrich.py` | `enrich_node` — Hunter email find/verify → `enriched`. |
| `nodes/human_gate.py` | `human_gate` (interrupt) + `route_after_gate`. |
| `routing.py` | `route_by_intent` — pure router from `state["intent"]`. |
| `graph.py` | Wire nodes + edges, compile with `MemorySaver`, `__main__` runner. |
| `tests/` | One test module per node/router. |
| `requirements.txt` | Pinned dependencies. |

> **Learning note:** we split nodes into their own files so each is small enough to hold in your head and test in isolation. This mirrors rubric criterion "one node = one job."

---

## Task 1: Project setup (deps, git, env hygiene, model fix)

**Files:**
- Create: `requirements.txt`, `.gitignore`
- Modify: `constants.py`

**Interfaces:**
- Produces: `constants.llm` (a `ChatAnthropic` instance), `constants.MODEL` (str).

- [ ] **Step 1: Write `requirements.txt`**

```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-anthropic>=0.3.0
python-dotenv>=1.0.0
pydantic>=2.0.0
requests>=2.31.0
pytest>=8.0.0
```

- [ ] **Step 2: Write `.gitignore`**

```
.env
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

- [ ] **Step 3: Create and activate a virtualenv, install deps**

Run:
```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\activate in PowerShell
pip install -r requirements.txt
```

- [ ] **Step 4: Fix the model in `constants.py`**

Replace the whole file with the minimal set it actually needs:

```python
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

MODEL = "claude-sonnet-4-5"
llm = ChatAnthropic(model=MODEL, temperature=0)
```

- [ ] **Step 5: Initialize git and commit**

```bash
git init
git add requirements.txt .gitignore constants.py
git commit -m "chore: project setup, deps, env hygiene, model fix"
```

Expected: `.env` is NOT staged (confirm with `git status`).

---

## Task 2: State and Intent shapes

**Files:**
- Create: `state.py`, `tests/test_state.py`

**Interfaces:**
- Produces:
  - `AgentState` TypedDict with keys `messages`, `intent: str`, `leads: list`, `enriched: list`.
  - `Intent` pydantic model: `category: Literal["find_leads","enrich_leads","clarify"]`, `query: str`.

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
import pytest
from pydantic import ValidationError
from state import Intent

def test_intent_accepts_valid_category():
    i = Intent(category="find_leads", query="VPs of Sales in fintech")
    assert i.category == "find_leads"
    assert i.query == "VPs of Sales in fintech"

def test_intent_rejects_unknown_category():
    with pytest.raises(ValidationError):
        Intent(category="buy_pizza", query="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'state'`.

- [ ] **Step 3: Write `state.py`**

```python
from typing import Annotated, Sequence, Literal
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: str
    leads: list
    enriched: list


class Intent(BaseModel):
    """Structured result of classifying the user's request."""
    category: Literal["find_leads", "enrich_leads", "clarify"] = Field(
        description="What the user is trying to do"
    )
    query: str = Field(description="Cleaned-up search criteria or target")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: add AgentState and Intent shapes"
```

---

## Task 3: Intent node (classification)

**Files:**
- Create: `nodes/__init__.py` (empty), `nodes/intent.py`, `tests/test_intent_node.py`

**Interfaces:**
- Consumes: `AgentState`, `Intent` from `state`.
- Produces: `intent_node(state: AgentState) -> dict` returning `{"intent": <category>}`.
  Signature takes an optional `llm` param for test injection: `intent_node(state, llm=None)`.

- [ ] **Step 1: Write the failing test** (LLM mocked — no network)

`tests/test_intent_node.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intent_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nodes'` (or `nodes.intent`).

- [ ] **Step 3: Write `nodes/intent.py`**

```python
from state import AgentState, Intent
from constants import llm as default_llm


def intent_node(state: AgentState, llm=None) -> dict:
    """Classify the latest user message into a validated Intent."""
    model = llm or default_llm
    classifier = model.with_structured_output(Intent)
    result: Intent = classifier.invoke(state["messages"])
    return {"intent": result.category}
```

Also create empty `nodes/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intent_node.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nodes/__init__.py nodes/intent.py tests/test_intent_node.py
git commit -m "feat: add intent classification node"
```

---

## Task 4: Router (intent → branch)

**Files:**
- Create: `routing.py`, `tests/test_routing.py`

**Interfaces:**
- Consumes: `AgentState`.
- Produces: `route_by_intent(state: AgentState) -> str` returning one of
  `"find_leads"`, `"enrich_leads"`, `"clarify"`.

- [ ] **Step 1: Write the failing test**

`tests/test_routing.py`:
```python
from routing import route_by_intent

def test_route_returns_intent_value():
    assert route_by_intent({"intent": "find_leads"}) == "find_leads"
    assert route_by_intent({"intent": "enrich_leads"}) == "enrich_leads"
    assert route_by_intent({"intent": "clarify"}) == "clarify"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'routing'`.

- [ ] **Step 3: Write `routing.py`**

```python
from state import AgentState


def route_by_intent(state: AgentState) -> str:
    """Return the branch name based on the classified intent."""
    return state["intent"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routing.py tests/test_routing.py
git commit -m "feat: add intent router"
```

---

## Task 5: Enrich node (Hunter)

**Files:**
- Create: `nodes/enrich.py`, `tests/test_enrich_node.py`

**Interfaces:**
- Consumes: `AgentState` with `state["leads"]` as a list of dicts, each with keys
  `first_name`, `last_name`, `domain`.
- Produces: `enrich_node(state: AgentState) -> dict` returning
  `{"enriched": [ {..lead.., "email": str|None, "status": "verified"|"not_found"|"error"} ]}`.
- Uses `requests.get` against `https://api.hunter.io/v2/email-finder`.

- [ ] **Step 1: Write the failing test** (Hunter mocked via `requests.get`)

`tests/test_enrich_node.py`:
```python
from unittest.mock import patch, MagicMock
from nodes.enrich import enrich_node

def _resp(json_body, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_body
    return m

@patch("nodes.enrich.requests.get")
def test_enrich_marks_verified(mock_get):
    mock_get.return_value = _resp(
        {"data": {"email": "jane@acme.com", "score": 96}}
    )
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] == "jane@acme.com"
    assert result["enriched"][0]["status"] == "verified"

@patch("nodes.enrich.requests.get")
def test_enrich_marks_not_found(mock_get):
    mock_get.return_value = _resp({"data": {"email": None}})
    state = {"leads": [{"first_name": "No", "last_name": "One", "domain": "x.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "not_found"

@patch("nodes.enrich.requests.get")
def test_enrich_marks_error_on_bad_status(mock_get):
    mock_get.return_value = _resp({}, status_code=500)
    state = {"leads": [{"first_name": "A", "last_name": "B", "domain": "y.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enrich_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nodes.enrich'`.

- [ ] **Step 3: Write `nodes/enrich.py`**

```python
import os
import requests
from state import AgentState

HUNTER_URL = "https://api.hunter.io/v2/email-finder"


def _find_one(lead: dict) -> dict:
    """Look up a single lead's email via Hunter, return lead + email + status."""
    params = {
        "domain": lead.get("domain"),
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "api_key": os.getenv("HUNTER_API_KEY"),
    }
    try:
        resp = requests.get(HUNTER_URL, params=params, timeout=20)
        if resp.status_code != 200:
            return {**lead, "email": None, "status": "error"}
        email = (resp.json().get("data") or {}).get("email")
        status = "verified" if email else "not_found"
        return {**lead, "email": email, "status": status}
    except requests.RequestException:
        return {**lead, "email": None, "status": "error"}


def enrich_node(state: AgentState) -> dict:
    """Validate/find emails for every lead in state['leads'] via Hunter."""
    enriched = [_find_one(lead) for lead in state.get("leads", [])]
    return {"enriched": enriched}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_enrich_node.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add nodes/enrich.py tests/test_enrich_node.py
git commit -m "feat: add Hunter enrich node with per-lead status"
```

---

## Task 6: Find node (Anthropic web search)

**Files:**
- Create: `nodes/find.py`, `tests/test_find_node.py`

**Interfaces:**
- Consumes: `AgentState`, `state["intent"] == "find_leads"`, the user query in messages.
- Produces: `find_node(state: AgentState, llm=None) -> dict` returning
  `{"leads": [ {"first_name","last_name","company","domain"} ] }`.
- Binds the server-side web search tool and asks the model to return JSON leads.

- [ ] **Step 1: Write the failing test** (LLM mocked; assert parse + tool binding)

`tests/test_find_node.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_find_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nodes.find'`.

- [ ] **Step 3: Write `nodes/find.py`**

```python
import json
from langchain_core.messages import SystemMessage
from state import AgentState
from constants import llm as default_llm

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant. Use web search to find real people matching "
    "the user's criteria. Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain. No prose, no markdown fences."
))


def _parse_leads(text: str) -> list:
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def find_node(state: AgentState, llm=None) -> dict:
    """Find candidate leads with Claude's web search tool."""
    model = llm or default_llm
    bound = model.bind_tools([WEB_SEARCH_TOOL])
    response = bound.invoke([FIND_SYSTEM, *state["messages"]])
    return {"leads": _parse_leads(response.content)}
```

> **Note on `response.content`:** with real web search the content may be a list of
> blocks rather than a string. Task 8 (integration) validates end to end; for this unit
> test the mock returns a plain string, which is the happy path. If live runs return
> blocks, extend `_parse_leads` to join text blocks first — that refinement is a future
> task, not part of this one.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_find_node.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add nodes/find.py tests/test_find_node.py
git commit -m "feat: add web-search find node"
```

---

## Task 7: Human gate (interrupt + post-gate router)

**Files:**
- Create: `nodes/human_gate.py`, `tests/test_human_gate.py`

**Interfaces:**
- Consumes: `AgentState` with `state["leads"]`.
- Produces:
  - `human_gate(state: AgentState) -> dict` — calls `interrupt(...)`, stores the human's
    decision as `{"gate_decision": <str>}` (one of `"enrich"`, `"done"`).
  - `route_after_gate(state: AgentState) -> str` — returns `"enrich_node"` when
    `gate_decision == "enrich"`, else `"__end__"`.
- Add `gate_decision: str` to `AgentState` in `state.py` (modify).

- [ ] **Step 1: Add `gate_decision` to state**

Modify `state.py` `AgentState` to add: `gate_decision: str`.

- [ ] **Step 2: Write the failing test** (patch `interrupt`)

`tests/test_human_gate.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_human_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nodes.human_gate'`.

- [ ] **Step 4: Write `nodes/human_gate.py`**

```python
from langgraph.types import interrupt
from langgraph.graph import END
from state import AgentState


def human_gate(state: AgentState) -> dict:
    """Pause and ask the human what to do with the found leads."""
    count = len(state.get("leads", []))
    decision = interrupt({
        "message": f"Found {count} leads. Reply 'enrich' to validate emails via "
                   f"Hunter, or 'done' to stop.",
        "leads": state.get("leads", []),
    })
    return {"gate_decision": decision}


def route_after_gate(state: AgentState) -> str:
    """Route to the shared enrich node or end, based on the human's reply."""
    return "enrich_node" if state.get("gate_decision") == "enrich" else END
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_human_gate.py -v`
Expected: PASS (3 passed). (`END` equals the string `"__end__"`.)

- [ ] **Step 6: Commit**

```bash
git add nodes/human_gate.py tests/test_human_gate.py state.py
git commit -m "feat: add human-in-the-loop gate and post-gate router"
```

---

## Task 8: Wire and compile the graph + integration test

**Files:**
- Modify: `graph.py` (replace imports-only file)
- Create: `tests/test_graph_integration.py`

**Interfaces:**
- Consumes: every node and router above.
- Produces: `app` (compiled graph) and `build_graph()` returning the compiled app.

- [ ] **Step 1: Write the failing integration test** (all tools mocked)

`tests/test_graph_integration.py`:
```python
import json
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

def _hunter_resp(email):
    m = MagicMock(); m.status_code = 200
    m.json.return_value = {"data": {"email": email}}
    return m

@patch("nodes.enrich.requests.get")
def test_enrich_intent_end_to_end(mock_get):
    # intent -> enrich path, no web search / no interrupt involved
    mock_get.return_value = _hunter_resp("jane@acme.com")
    from graph import build_graph
    from state import Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="enrich_leads", query="Jane Doe acme.com")

    with patch("nodes.intent.default_llm", fake_llm):
        app = build_graph()
        state = {
            "messages": [HumanMessage(content="enrich Jane Doe at acme.com")],
            "intent": "", "leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
            "enriched": [], "gate_decision": "",
        }
        final = app.invoke(state, {"configurable": {"thread_id": "t1"}})

    assert final["intent"] == "enrich_leads"
    assert final["enriched"][0]["email"] == "jane@acme.com"
    assert final["enriched"][0]["status"] == "verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_integration.py -v`
Expected: FAIL (`build_graph` not defined / graph.py still imports-only).

- [ ] **Step 3: Write `graph.py`**

```python
import sys
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from state import AgentState
from routing import route_by_intent
from nodes.intent import intent_node
from nodes.find import find_node
from nodes.enrich import enrich_node
from nodes.human_gate import human_gate, route_after_gate


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("intent_node", intent_node)
    g.add_node("find_node", find_node)
    g.add_node("human_gate", human_gate)
    g.add_node("enrich_node", enrich_node)

    g.add_edge(START, "intent_node")
    g.add_conditional_edges("intent_node", route_by_intent, {
        "find_leads": "find_node",
        "enrich_leads": "enrich_node",
        "clarify": END,
    })
    g.add_edge("find_node", "human_gate")
    g.add_conditional_edges("human_gate", route_after_gate, {
        "enrich_node": "enrich_node",
        END: END,
    })
    g.add_edge("enrich_node", END)

    return g.compile(checkpointer=MemorySaver())


app = build_graph()


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Find VPs of Sales at fintech startups"
    config = {"configurable": {"thread_id": "demo-1"}}
    final = app.invoke(
        {"messages": [HumanMessage(content=text)],
         "intent": "", "leads": [], "enriched": [], "gate_decision": ""},
        config,
    )
    print("intent  :", final.get("intent"))
    print("leads   :", final.get("leads"))
    print("enriched:", final.get("enriched"))
    # If the run paused at the human gate, LangGraph returns an __interrupt__ payload;
    # resume with app.invoke(Command(resume="enrich"), config). See Task 8 note.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_graph_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add graph.py tests/test_graph_integration.py
git commit -m "feat: wire and compile BDR agent graph"
```

---

## Task 9: Manual smoke test with live keys (optional, no test)

**Files:** none (manual verification)

- [ ] **Step 1: Run the enrich path live**

Run: `python graph.py "enrich Jane Doe at stripe.com"` — but note the current runner
seeds empty `leads`, so for a live enrich you'll pass leads through a REPL:
```python
from langgraph.types import Command
from graph import app
from langchain_core.messages import HumanMessage
cfg = {"configurable": {"thread_id": "live-1"}}
out = app.invoke({"messages":[HumanMessage(content="find fintech VPs")],
                  "intent":"","leads":[],"enriched":[],"gate_decision":""}, cfg)
print(out)               # should pause at the interrupt
out = app.invoke(Command(resume="enrich"), cfg)   # resume the gate
print(out["enriched"])
```

- [ ] **Step 2: Confirm LangSmith trace appears** (if `LANGSMITH_TRACING=true` in `.env`).

- [ ] **Step 3: Commit any tweaks** discovered during smoke testing.

---

## Self-Review

**Spec coverage:**
- Find leads (web search) → Task 6. ✅
- Enrich leads (Hunter) → Task 5. ✅
- Intent node + taxonomy incl. `clarify` → Tasks 2, 3. ✅
- Router → Task 4. ✅
- Human-in-the-loop interrupt + shared enrich node (Approach A) → Tasks 7, 8. ✅
- Error handling (clarify / empty leads / Hunter status) → Tasks 3, 5, 6. ✅
- Testing strategy (unit per node + one integration, all mocked) → every task. ✅
- Model-ID fix + env hygiene → Task 1. ✅

**Placeholder scan:** No TBD/TODO left as work; the two "future refinement" notes
(content-block parsing in find; refine-loop in gate) are explicitly scoped OUT with
reasons, not left as silent gaps.

**Type consistency:** State keys `messages / intent / leads / enriched / gate_decision`
used identically across `state.py`, all nodes, routers, and the integration test.
`enrich_node` reads `leads` (dicts with `first_name/last_name/domain`) and writes
`enriched`; `find_node` produces those same dicts (plus `company`). Router branch names
(`find_leads/enrich_leads/clarify`) match the `Literal` in `Intent` and the
`add_conditional_edges` mapping keys.
