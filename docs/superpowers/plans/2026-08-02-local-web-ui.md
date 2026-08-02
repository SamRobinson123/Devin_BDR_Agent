# Local Web UI for the BDR Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web UI (FastAPI backend + React/Vite frontend + SQLite
persistence) around the existing `graph.py` BDR agent, per
`docs/superpowers/specs/2026-08-02-local-web-ui-design.md`.

**Architecture:** A `db.py` module owns a SQLite `leads` table (plain CRUD, no ORM). The
compiled graph in `graph.py` switches its checkpointer from `MemorySaver` to
`SqliteSaver` (same on-disk file) so a paused human-gate interrupt survives a backend
restart. A FastAPI app (`server.py`) exposes `/chat`, `/leads`, `/leads/upload`,
`/leads/enrich`, calling into `graph.py` and `db.py`. A Vite + React frontend
(`frontend/`) has two tabbed pages — Chat and Leads Database — that call this API.

**Tech Stack:** Python (FastAPI, uvicorn, python-multipart, langgraph-checkpoint-sqlite,
pytest, httpx for TestClient), React + Vite (vitest, @testing-library/react).

## Global Constraints

- `graph.py`'s node functions (`intent_node`, `find_node`, `enrich_node`,
  `apollo_phone_node`, `human_gate`, `route_by_intent`, `route_after_gate`) are NOT
  modified — only `build_graph()`'s checkpointer argument changes.
- One SQLite file holds both the `leads` table and LangGraph's checkpoint tables.
- `leads` table upsert key is `(first_name, last_name, domain)` — never insert
  duplicate rows for the same person.
- CSV upload required columns: `first_name`, `last_name`, `domain` (`company` optional).
  Invalid rows are reported individually, never abort the whole upload.
- Every backend test mocks `graph.llm` and `requests` — no live API calls in the test
  suite (matches the existing `tests/` pattern in this repo).
- Frontend generates one `thread_id` (UUID) per browser session, stored in
  `localStorage`, reused for every `/chat` call in that session.
- No real-time/websocket push — the leads table refetches after actions complete.

---

## File Structure

| File | Responsibility |
|---|---|
| `db.py` | SQLite schema init + `leads` table CRUD (upsert, list, get-by-ids, update-enrichment, CSV-row insert with validation). |
| `graph.py` | Modified: `build_graph()` takes the `SqliteSaver` checkpointer instead of `MemorySaver`. No other changes. |
| `server.py` | FastAPI app: `/chat`, `/leads`, `/leads/upload`, `/leads/enrich`. |
| `tests/test_db.py` | Unit tests for `db.py`. |
| `tests/test_server.py` | FastAPI `TestClient` tests for all four endpoints, mocked graph/requests. |
| `frontend/src/App.jsx` | Tab navigation between Chat and Leads Database pages. |
| `frontend/src/api.js` | Thin fetch wrappers for the four backend endpoints. |
| `frontend/src/pages/Chat.jsx` | Chat page: message list, input, gate buttons. |
| `frontend/src/pages/LeadsDatabase.jsx` | Leads table, CSV upload, select + enrich. |
| `frontend/src/pages/Chat.test.jsx` | Component tests for gate buttons + message flow. |
| `frontend/src/pages/LeadsDatabase.test.jsx` | Component tests for table rendering + enrich action. |

---

## Task 1: SQLite leads persistence (`db.py`)

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `init_db(path: str) -> sqlite3.Connection` — creates the `leads` table if absent, returns an open connection.
  - `upsert_lead(conn, lead: dict) -> int` — insert or update by `(first_name, last_name, domain)`, returns the row id.
  - `list_leads(conn, status: str | None = None) -> list[dict]` — all rows, optionally filtered by `status`.
  - `get_leads_by_ids(conn, ids: list[int]) -> list[dict]`.
  - `update_lead_enrichment(conn, lead_id: int, email, status, phone, phone_status) -> None`.
  - `insert_csv_rows(conn, rows: list[dict]) -> dict` — returns `{"inserted": int, "errors": [{"row": int, "reason": str}]}`.

- [ ] **Step 1: Write the failing tests for schema + upsert**

`tests/test_db.py`:
```python
import sqlite3
import pytest
from db import init_db, upsert_lead, list_leads


@pytest.fixture
def conn():
    return init_db(":memory:")


def test_init_db_creates_leads_table(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
    assert cur.fetchone() is not None


def test_upsert_lead_inserts_new_row(conn):
    lead_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                  "domain": "acme.com", "company": "Acme",
                                  "source": "chat"})
    rows = list_leads(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == lead_id
    assert rows[0]["status"] == "pending"


def test_upsert_lead_updates_existing_row_not_duplicate(conn):
    first_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                   "domain": "acme.com", "company": "Acme",
                                   "source": "chat"})
    second_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                    "domain": "acme.com", "company": "Acme Corp",
                                    "source": "chat"})
    rows = list_leads(conn)
    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme Corp"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`.

- [ ] **Step 3: Write `db.py` schema + `init_db` + `upsert_lead` + `list_leads`**

```python
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    company TEXT,
    domain TEXT,
    email TEXT,
    status TEXT DEFAULT 'pending',
    phone TEXT,
    phone_status TEXT DEFAULT 'pending',
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(first_name, last_name, domain)
)
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def upsert_lead(conn: sqlite3.Connection, lead: dict) -> int:
    now = _now()
    existing = conn.execute(
        "SELECT id FROM leads WHERE first_name = ? AND last_name = ? AND domain = ?",
        (lead.get("first_name"), lead.get("last_name"), lead.get("domain")),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE leads SET company = ?, updated_at = ? WHERE id = ?",
            (lead.get("company"), now, existing["id"]),
        )
        conn.commit()
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO leads (first_name, last_name, company, domain, source, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lead.get("first_name"), lead.get("last_name"), lead.get("company"),
         lead.get("domain"), lead.get("source"), now, now),
    )
    conn.commit()
    return cur.lastrowid


def list_leads(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute("SELECT * FROM leads WHERE status = ?", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads").fetchall()
    return [_row_to_dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the failing tests for `get_leads_by_ids` and `update_lead_enrichment`**

Append to `tests/test_db.py`:
```python
from db import get_leads_by_ids, update_lead_enrichment


def test_get_leads_by_ids_returns_matching_rows(conn):
    id1 = upsert_lead(conn, {"first_name": "A", "last_name": "B", "domain": "a.com", "source": "chat"})
    id2 = upsert_lead(conn, {"first_name": "C", "last_name": "D", "domain": "c.com", "source": "chat"})
    rows = get_leads_by_ids(conn, [id1, id2])
    assert {r["id"] for r in rows} == {id1, id2}


def test_update_lead_enrichment_writes_email_and_phone(conn):
    lead_id = upsert_lead(conn, {"first_name": "A", "last_name": "B", "domain": "a.com", "source": "chat"})
    update_lead_enrichment(conn, lead_id, email="a.b@a.com", status="verified",
                            phone="+1-555-0100", phone_status="found")
    row = get_leads_by_ids(conn, [lead_id])[0]
    assert row["email"] == "a.b@a.com"
    assert row["status"] == "verified"
    assert row["phone"] == "+1-555-0100"
    assert row["phone_status"] == "found"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_leads_by_ids'`.

- [ ] **Step 7: Implement `get_leads_by_ids` and `update_lead_enrichment`**

Append to `db.py`:
```python
def get_leads_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM leads WHERE id IN ({placeholders})", ids).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_lead_enrichment(conn: sqlite3.Connection, lead_id: int, email, status,
                            phone, phone_status) -> None:
    conn.execute(
        "UPDATE leads SET email = ?, status = ?, phone = ?, phone_status = ?, "
        "updated_at = ? WHERE id = ?",
        (email, status, phone, phone_status, _now(), lead_id),
    )
    conn.commit()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (5 passed).

- [ ] **Step 9: Write the failing tests for `insert_csv_rows`**

Append to `tests/test_db.py`:
```python
from db import insert_csv_rows


def test_insert_csv_rows_inserts_valid_rows(conn):
    rows = [
        {"first_name": "Jane", "last_name": "Doe", "domain": "acme.com", "company": "Acme"},
        {"first_name": "No", "last_name": "Domain", "domain": ""},
    ]
    result = insert_csv_rows(conn, rows)
    assert result["inserted"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row"] == 1
    all_leads = list_leads(conn)
    assert len(all_leads) == 1
    assert all_leads[0]["source"] == "csv_upload"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_csv_rows'`.

- [ ] **Step 11: Implement `insert_csv_rows`**

Append to `db.py`:
```python
def insert_csv_rows(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    inserted = 0
    errors = []
    for i, row in enumerate(rows):
        if not (row.get("first_name") and row.get("last_name") and row.get("domain")):
            errors.append({"row": i, "reason": "missing required field (first_name, last_name, domain)"})
            continue
        upsert_lead(conn, {**row, "source": "csv_upload"})
        inserted += 1
    return {"inserted": inserted, "errors": errors}
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (6 passed).

- [ ] **Step 13: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add SQLite leads persistence module"
```

---

## Task 2: Switch graph.py to a persistent SqliteSaver checkpointer

**Files:**
- Modify: `graph.py` (the `build_graph()` function and module-level `app = build_graph()`)
- Test: `tests/test_graph_persistence.py`

**Interfaces:**
- Consumes: `graph.build_graph`, `graph.AgentState`.
- Produces: `build_graph(checkpointer=None)` — if no checkpointer is passed, creates a
  `SqliteSaver` backed by `AGENT_DB_PATH` (new module-level constant in `graph.py`,
  default `"agent.db"`, overridable via env var `AGENT_DB_PATH`).

- [ ] **Step 1: Add the dependency**

```bash
pip install langgraph-checkpoint-sqlite
```

- [ ] **Step 2: Write the failing test**

`tests/test_graph_persistence.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_graph_persistence.py -v`
Expected: FAIL — state from `app1` not visible to `app2` (both currently use separate
in-memory `MemorySaver` instances since `build_graph()` creates a fresh one each call).

- [ ] **Step 4: Update `graph.py`'s imports and `build_graph()`**

Add near the top imports (after `from langgraph.checkpoint.memory import MemorySaver`,
which can now be removed):
```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
```

Add a module-level constant right after the other top-level constants (near
`WEB_SEARCH_TOOL`/`VERIFIER_URL`, or just under the imports):
```python
AGENT_DB_PATH = os.getenv("AGENT_DB_PATH", "agent.db")
```

Replace the `build_graph()` function's final lines:
```python
def build_graph(checkpointer=None):
    g = StateGraph(AgentState)
    ... (all existing add_node/add_edge calls, unchanged) ...

    if checkpointer is None:
        conn = sqlite3.connect(AGENT_DB_PATH, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        checkpointer.setup()

    return g.compile(checkpointer=checkpointer)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_graph_persistence.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full existing test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests pass (the existing `tests/test_graph_integration.py` builds its own
graph via `build_graph()` with no explicit checkpointer, so it now uses a real
`agent.db` file in the repo root during that test run — confirm this is acceptable or,
if not, have that test pass `checkpointer=MemorySaver()` explicitly since the
`checkpointer` parameter now supports injection for tests).

- [ ] **Step 7: If Step 6 revealed the integration test writing a stray `agent.db`, pin it to an in-memory checkpointer**

In `tests/test_graph_integration.py`, change:
```python
app = build_graph()
```
to:
```python
from langgraph.checkpoint.memory import MemorySaver
app = build_graph(checkpointer=MemorySaver())
```

Run: `pytest tests/test_graph_integration.py -v`
Expected: PASS, and no `agent.db` file appears in the repo root after the run.

- [ ] **Step 8: Add `agent.db` to `.gitignore`**

Append to `.gitignore`:
```
agent.db
```

- [ ] **Step 9: Commit**

```bash
git add graph.py tests/test_graph_persistence.py tests/test_graph_integration.py .gitignore requirements.txt
git commit -m "feat: persist graph checkpoints via SqliteSaver"
```

---

## Task 3: FastAPI app skeleton + GET /leads

**Files:**
- Create: `server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `db.init_db`, `db.list_leads`.
- Produces: `server.app` (FastAPI instance), `GET /leads` endpoint returning
  `list[dict]` matching `db.list_leads`'s shape.

- [ ] **Step 1: Install dependencies**

```bash
pip install fastapi uvicorn python-multipart httpx
```

- [ ] **Step 2: Write the failing test**

`tests/test_server.py`:
```python
from fastapi.testclient import TestClient


def test_get_leads_returns_empty_list_initially(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    resp = client.get("/leads")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'`.

- [ ] **Step 4: Write `server.py`**

```python
import os
from fastapi import FastAPI

from db import init_db, list_leads

LEADS_DB_PATH = os.getenv("LEADS_DB_PATH", "leads.db")

app = FastAPI()
db_conn = init_db(LEADS_DB_PATH)


@app.get("/leads")
def get_leads(status: str | None = None):
    return list_leads(db_conn, status=status)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py requirements.txt
git commit -m "feat: add FastAPI app skeleton with GET /leads"
```

---

## Task 4: POST /leads/upload

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `db.insert_csv_rows`.
- Produces: `POST /leads/upload` (multipart CSV file) → `{"inserted": int, "errors": [...]}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:
```python
import io


def test_upload_csv_inserts_valid_rows_and_reports_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads2.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    csv_content = (
        "first_name,last_name,domain,company\n"
        "Jane,Doe,acme.com,Acme\n"
        "No,Domain,,Missing Domain Co\n"
    )
    files = {"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    resp = client.post("/leads/upload", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 1
    assert len(body["errors"]) == 1

    leads = client.get("/leads").json()
    assert len(leads) == 1
    assert leads[0]["source"] == "csv_upload"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — 404 Not Found (no `/leads/upload` route yet).

- [ ] **Step 3: Add the endpoint to `server.py`**

```python
import csv
import io
from fastapi import UploadFile, File

from db import insert_csv_rows


@app.post("/leads/upload")
async def upload_leads(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    return insert_csv_rows(db_conn, rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add CSV upload endpoint for leads"
```

---

## Task 5: POST /leads/enrich

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `db.get_leads_by_ids`, `db.update_lead_enrichment`, `graph.enrich_node`,
  `graph.apollo_phone_node`.
- Produces: `POST /leads/enrich` (body `{"lead_ids": [int]}`) → updated rows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:
```python
from unittest.mock import patch, MagicMock


def _verifier_resp(result, email):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": {"result": result, "email": email}}
    m.raise_for_status.return_value = None
    return m


@patch("graph.requests.get")
def test_enrich_endpoint_updates_db_rows(mock_get, tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads3.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    csv_content = "first_name,last_name,domain,company\nJane,Doe,acme.com,Acme\n"
    files = {"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    client.post("/leads/upload", files=files)
    lead_id = client.get("/leads").json()[0]["id"]

    mock_get.return_value = _verifier_resp("deliverable", "jane.doe@acme.com")
    resp = client.post("/leads/enrich", json={"lead_ids": [lead_id]})

    assert resp.status_code == 200
    updated = client.get("/leads").json()[0]
    assert updated["email"] == "jane.doe@acme.com"
    assert updated["status"] == "verified"
    assert updated["phone_status"] == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — 404 Not Found (no `/leads/enrich` route yet).

- [ ] **Step 3: Add the endpoint to `server.py`**

```python
from pydantic import BaseModel

from db import get_leads_by_ids, update_lead_enrichment
from graph import enrich_node, apollo_phone_node


class EnrichRequest(BaseModel):
    lead_ids: list[int]


@app.post("/leads/enrich")
def enrich_leads(req: EnrichRequest):
    rows = get_leads_by_ids(db_conn, req.lead_ids)
    email_result = enrich_node({"leads": rows})
    phone_result = apollo_phone_node({"enriched": email_result["enriched"]})
    for lead in phone_result["enriched"]:
        update_lead_enrichment(
            db_conn, lead["id"], lead.get("email"), lead.get("status"),
            lead.get("phone"), lead.get("phone_status"),
        )
    return get_leads_by_ids(db_conn, req.lead_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add /leads/enrich endpoint"
```

---

## Task 6: POST /chat

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `graph.app` (compiled graph), `db.upsert_lead`.
- Produces: `POST /chat` (body `{"message": str, "thread_id": str}`) →
  `{"reply": str, "leads": list | None, "paused": bool, "gate_message": str | None}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:
```python
from langchain_core.messages import AIMessage


@patch("graph.llm")
def test_chat_find_intent_saves_leads_and_pauses(mock_llm, tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads4.db"))
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test_agent4.db"))
    import importlib
    import server
    importlib.reload(server)
    from graph import Intent

    structured = MagicMock()
    mock_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    bound = MagicMock()
    mock_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=(
        '[{"first_name": "Jane", "last_name": "Doe", "company": "Acme", "domain": "acme.com"}]'
    ))

    client = TestClient(server.app)
    resp = client.post("/chat", json={"message": "find fintech VPs", "thread_id": "t1"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["paused"] is True
    assert "Jane" in body["gate_message"] or body["leads"][0]["first_name"] == "Jane"

    saved = client.get("/leads").json()
    assert len(saved) == 1
    assert saved[0]["first_name"] == "Jane"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — 404 Not Found (no `/chat` route yet).

- [ ] **Step 3: Add the endpoint to `server.py`**

```python
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from graph import app as compiled_graph


class ChatRequest(BaseModel):
    message: str
    thread_id: str


def _is_paused(config: dict) -> bool:
    snapshot = compiled_graph.get_state(config)
    return bool(snapshot.next)


@app.post("/chat")
def chat(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    if _is_paused(config):
        result = compiled_graph.invoke(Command(resume=req.message), config)
    else:
        result = compiled_graph.invoke(
            {"messages": [HumanMessage(content=req.message)], "intent": "",
             "leads": [], "enriched": [], "gate_decision": ""},
            config,
        )

    for lead in result.get("leads", []):
        upsert_lead(db_conn, {**lead, "source": "chat"})

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        return {
            "reply": payload["message"],
            "leads": payload["leads"],
            "paused": True,
            "gate_message": payload["message"],
        }

    return {
        "reply": f"Done. Intent: {result.get('intent')}",
        "leads": result.get("enriched") or result.get("leads"),
        "paused": False,
        "gate_message": None,
    }
```

Add the `upsert_lead` import at the top alongside the other `db` imports:
```python
from db import init_db, list_leads, insert_csv_rows, get_leads_by_ids, update_lead_enrichment, upsert_lead
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -v`
Expected: all tests pass (original graph tests + db tests + server tests).

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add /chat endpoint wiring the compiled graph to the leads DB"
```

---

## Task 7: Frontend scaffold + tab navigation

**Files:**
- Create: `frontend/` (via `npm create vite@latest`)
- Create: `frontend/src/App.jsx`
- Create: `frontend/src/api.js`

**Interfaces:**
- Produces: `App` component rendering a top nav with "Chat" / "Leads Database" tabs,
  and `api.js` exporting `sendChat`, `getLeads`, `uploadLeadsCsv`, `enrichLeads`.

- [ ] **Step 1: Scaffold the Vite React project**

```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Configure vitest**

Add to `frontend/vite.config.js`:
```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
  },
})
```

Create `frontend/src/setupTests.js`:
```javascript
import '@testing-library/jest-dom'
```

Add to `frontend/package.json` scripts:
```json
"test": "vitest run"
```

- [ ] **Step 3: Write `frontend/src/api.js`**

```javascript
const BASE_URL = 'http://localhost:8000'

export async function sendChat(message, threadId) {
  const resp = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
  })
  return resp.json()
}

export async function getLeads() {
  const resp = await fetch(`${BASE_URL}/leads`)
  return resp.json()
}

export async function uploadLeadsCsv(file) {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch(`${BASE_URL}/leads/upload`, { method: 'POST', body: formData })
  return resp.json()
}

export async function enrichLeads(leadIds) {
  const resp = await fetch(`${BASE_URL}/leads/enrich`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lead_ids: leadIds }),
  })
  return resp.json()
}
```

- [ ] **Step 4: Write `frontend/src/App.jsx`**

```jsx
import { useState } from 'react'
import Chat from './pages/Chat'
import LeadsDatabase from './pages/LeadsDatabase'

export default function App() {
  const [tab, setTab] = useState('chat')

  return (
    <div>
      <nav>
        <button onClick={() => setTab('chat')} aria-current={tab === 'chat'}>Chat</button>
        <button onClick={() => setTab('leads')} aria-current={tab === 'leads'}>Leads Database</button>
      </nav>
      {tab === 'chat' ? <Chat /> : <LeadsDatabase />}
    </div>
  )
}
```

- [ ] **Step 5: Verify the dev server starts**

Run: `npm run dev` (in `frontend/`), confirm no build errors, then stop it (Ctrl+C).

- [ ] **Step 6: Commit**

```bash
cd frontend
git add package.json vite.config.js src/App.jsx src/api.js src/setupTests.js
git commit -m "feat: scaffold Vite React frontend with tab navigation"
```

---

## Task 8: Chat page component

**Files:**
- Create: `frontend/src/pages/Chat.jsx`
- Test: `frontend/src/pages/Chat.test.jsx`

**Interfaces:**
- Consumes: `sendChat` from `../api.js`.
- Produces: `Chat` component (default export).

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Chat.test.jsx`:
```jsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Chat from './Chat'
import * as api from '../api'

describe('Chat page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'sendChat')
  })

  it('shows Enrich/Done buttons when the response is paused', async () => {
    api.sendChat.mockResolvedValue({
      reply: 'Found 1 leads.', leads: [{ first_name: 'Jane' }],
      paused: true, gate_message: 'Found 1 leads. Reply enrich or done.',
    })

    render(<Chat />)
    fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
    fireEvent.click(screen.getByText(/send/i))

    await waitFor(() => expect(screen.getByText('Enrich')).toBeInTheDocument())
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('posts the button value as the next message when clicked', async () => {
    api.sendChat
      .mockResolvedValueOnce({ reply: 'Found 1 leads.', leads: [], paused: true, gate_message: 'x' })
      .mockResolvedValueOnce({ reply: 'Enriched.', leads: [], paused: false, gate_message: null })

    render(<Chat />)
    fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
    fireEvent.click(screen.getByText(/send/i))
    await waitFor(() => screen.getByText('Enrich'))

    fireEvent.click(screen.getByText('Enrich'))
    await waitFor(() => expect(api.sendChat).toHaveBeenLastCalledWith('enrich', expect.any(String)))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test` (in `frontend/`)
Expected: FAIL — `Chat.jsx` does not exist.

- [ ] **Step 3: Write `frontend/src/pages/Chat.jsx`**

```jsx
import { useState } from 'react'
import { sendChat } from '../api'

function getThreadId() {
  let id = localStorage.getItem('thread_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('thread_id', id)
  }
  return id
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(null)
  const threadId = getThreadId()

  async function send(text) {
    setMessages((m) => [...m, { role: 'user', text }])
    const result = await sendChat(text, threadId)
    setMessages((m) => [...m, { role: 'agent', text: result.reply }])
    setPending(result.paused ? result : null)
  }

  return (
    <div>
      <div>
        {messages.map((m, i) => <div key={i}>{m.role}: {m.text}</div>)}
        {pending && (
          <div>
            <button onClick={() => send('enrich')}>Enrich</button>
            <button onClick={() => send('done')}>Done</button>
          </div>
        )}
      </div>
      {!pending && (
        <div>
          <input
            placeholder="Message the agent..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button onClick={() => { send(input); setInput('') }}>Send</button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/pages/Chat.jsx src/pages/Chat.test.jsx
git commit -m "feat: add Chat page with human-gate buttons"
```

---

## Task 9: Leads Database page component

**Files:**
- Create: `frontend/src/pages/LeadsDatabase.jsx`
- Test: `frontend/src/pages/LeadsDatabase.test.jsx`

**Interfaces:**
- Consumes: `getLeads`, `uploadLeadsCsv`, `enrichLeads` from `../api.js`.
- Produces: `LeadsDatabase` component (default export).

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/LeadsDatabase.test.jsx`:
```jsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import LeadsDatabase from './LeadsDatabase'
import * as api from '../api'

describe('LeadsDatabase page', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getLeads')
    vi.spyOn(api, 'enrichLeads')
  })

  it('renders leads in a table', async () => {
    api.getLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: null, status: 'pending', phone: null, phone_status: 'pending' },
    ])

    render(<LeadsDatabase />)
    await waitFor(() => expect(screen.getByText('Jane')).toBeInTheDocument())
    expect(screen.getByText('Acme')).toBeInTheDocument()
  })

  it('enriches selected pending leads', async () => {
    api.getLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: null, status: 'pending', phone: null, phone_status: 'pending' },
    ])
    api.enrichLeads.mockResolvedValue([
      { id: 1, first_name: 'Jane', last_name: 'Doe', company: 'Acme', domain: 'acme.com',
        email: 'jane@acme.com', status: 'verified', phone: null, phone_status: 'not_found' },
    ])

    render(<LeadsDatabase />)
    await waitFor(() => screen.getByText('Jane'))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByText(/enrich selected/i))

    await waitFor(() => expect(api.enrichLeads).toHaveBeenCalledWith([1]))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `LeadsDatabase.jsx` does not exist.

- [ ] **Step 3: Write `frontend/src/pages/LeadsDatabase.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { getLeads, uploadLeadsCsv, enrichLeads } from '../api'

export default function LeadsDatabase() {
  const [leads, setLeads] = useState([])
  const [selected, setSelected] = useState(new Set())

  async function refresh() {
    setLeads(await getLeads())
  }

  useEffect(() => { refresh() }, [])

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleUpload(e) {
    const file = e.target.files[0]
    if (file) {
      await uploadLeadsCsv(file)
      await refresh()
    }
  }

  async function handleEnrich() {
    await enrichLeads(Array.from(selected))
    setSelected(new Set())
    await refresh()
  }

  return (
    <div>
      <input type="file" accept=".csv" onChange={handleUpload} />
      <button onClick={handleEnrich} disabled={selected.size === 0}>Enrich Selected</button>
      <table>
        <thead>
          <tr>
            <th></th><th>Name</th><th>Company</th><th>Domain</th>
            <th>Email</th><th>Status</th><th>Phone</th><th>Phone Status</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => (
            <tr key={lead.id}>
              <td>
                {lead.status === 'pending' && (
                  <input type="checkbox" checked={selected.has(lead.id)} onChange={() => toggle(lead.id)} />
                )}
              </td>
              <td>{lead.first_name} {lead.last_name}</td>
              <td>{lead.company}</td>
              <td>{lead.domain}</td>
              <td>{lead.email}</td>
              <td>{lead.status}</td>
              <td>{lead.phone}</td>
              <td>{lead.phone_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/pages/LeadsDatabase.jsx src/pages/LeadsDatabase.test.jsx
git commit -m "feat: add Leads Database page with CSV upload and enrich action"
```

---

## Task 10: Manual end-to-end smoke test (optional, no automated test)

**Files:** none (manual verification)

- [ ] **Step 1: Start the backend**

```bash
uvicorn server:app --reload --port 8000
```

- [ ] **Step 2: Start the frontend**

```bash
cd frontend
npm run dev
```

- [ ] **Step 3: Walk through the flow in a browser**

1. Open the Chat tab, send "find a VP of sales at a well-known fintech company".
2. Confirm the paused message with Enrich/Done buttons appears.
3. Click Enrich; confirm the reply updates and the lead now has email/phone data.
4. Switch to Leads Database tab; confirm the lead appears in the table.
5. Upload a small CSV with 2-3 leads; confirm they appear as `pending`.
6. Select one, click "Enrich Selected"; confirm its row updates after the call
   completes.
7. Restart the backend (`Ctrl+C`, re-run `uvicorn ...`); confirm `GET /leads` still
   returns the previously saved leads (proves SQLite persistence survived the
   restart).

- [ ] **Step 4: Commit any fixes discovered during the smoke test**

---

## Self-Review

**Spec coverage:**
- Architecture (SQLite + FastAPI + React, checkpointer swap) → Tasks 1, 2, 3. ✅
- `leads` table schema → Task 1. ✅
- All four API endpoints → Tasks 3-6. ✅
- Chat page with inline gate buttons → Task 8. ✅
- Leads Database page with CSV upload + select/enrich → Task 9. ✅
- Error handling (CSV row validation, per-lead status pass-through) → Tasks 1, 4, 5. ✅
- Persistence surviving a restart → Task 2, verified manually in Task 10. ✅
- Testing strategy (backend TestClient + mocks, frontend component tests) → every task. ✅

**Placeholder scan:** No TBD/TODO. Task 10 is explicitly manual/optional per the
original graph plan's precedent (its own Task 9).

**Type consistency:** `db.py`'s `upsert_lead`/`get_leads_by_ids`/`update_lead_enrichment`
signatures match how `server.py` calls them in Tasks 4-6. `server.py`'s response shape
(`reply`/`leads`/`paused`/`gate_message`) matches what `Chat.jsx` destructures in Task 8.
`enrichLeads(leadIds)` in `api.js` matches the `lead_ids` field `EnrichRequest` expects
in Task 5, and matches the call in `LeadsDatabase.jsx`'s `handleEnrich`.
