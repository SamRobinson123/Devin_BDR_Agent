# Live Graph Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `POST /chat` to a Server-Sent-Events stream that emits one event per
completed graph node plus a final result event, and add a live `GraphPanel` component
to the Chat page that animates the agent's progress through the graph, per
`docs/superpowers/specs/2026-08-02-live-graph-visualization-design.md`.

**Architecture:** `server.py`'s `/chat` handler switches from `compiled_graph.invoke()`
to `compiled_graph.stream(..., stream_mode="updates")`, yielding an SSE `node` event
per completed node, then computing the same `{reply, leads, paused, gate_message}`
result it produces today (via `get_state()`) and yielding it as a final `result` event.
`api.js`'s `sendChat` switches from a plain `fetch().json()` call to reading the
response body as a stream and parsing SSE lines with a pure, independently-testable
parser function. A new `GraphPanel.jsx` renders the fixed node diagram and reacts to
node/result events passed to it from `Chat.jsx`.

**Tech Stack:** FastAPI `StreamingResponse`, LangGraph `stream(stream_mode="updates")`,
browser `fetch()` + `ReadableStream`, React.

## Global Constraints

- The `/chat` response contract for the final event (`reply`, `leads`, `paused`,
  `gate_message`) does not change shape — only how it's delivered (SSE `result` event
  instead of a plain JSON body).
- Pause detection continues to use `compiled_graph.get_state(config)` /
  `snapshot.next`, not an assumption about the `"__interrupt__"` key's shape inside
  the `stream_mode="updates"` output.
- The `intent_node`'s `node` SSE event MUST include its update payload
  (`{"node": "intent_node", "data": {"intent": "find_leads", ...}}`) so the frontend
  can resolve which branch (`find_node` vs `enrich_node`) to highlight next.
- SSE line parsing is implemented as a pure function, tested directly — not through
  a live streaming `fetch()` in tests (impractical in jsdom).
- All existing tests (26 backend, 4 frontend) must continue to pass unmodified where
  possible; `test_chat_find_intent_saves_leads_and_pauses` and
  `test_chat_enrich_after_gate_updates_db` in `tests/test_server.py` will need updating
  since `/chat`'s response is no longer a single JSON body (see Task 1).

---

## File Structure

| File | Responsibility |
|---|---|
| `server.py` | Modify: `/chat` becomes a streaming SSE endpoint. |
| `tests/test_server.py` | Modify: update the two `/chat` tests for the new SSE contract. |
| `frontend/src/api.js` | Modify: `sendChat` reads and parses the SSE stream. |
| `frontend/src/sse.js` | Create: pure SSE line-parsing function, used by `api.js`. |
| `frontend/src/sse.test.js` | Create: unit tests for the parser. |
| `frontend/src/pages/GraphPanel.jsx` | Create: the node-diagram component. |
| `frontend/src/pages/GraphPanel.test.jsx` | Create: component tests. |
| `frontend/src/pages/GraphPanel.css` | Create: node box / pulse / checkmark styles. |
| `frontend/src/pages/Chat.jsx` | Modify: owns the node-path state, renders `GraphPanel`, passes a node-event callback into `sendChat`. |
| `frontend/src/pages/Chat.test.jsx` | Modify: existing mocks of `sendChat` updated to the new callback-based signature. |

---

## Task 1: Convert `/chat` to an SSE stream (backend)

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Consumes: `graph.app` (`compiled_graph`), `db.upsert_lead`, `db.update_lead_enrichment`.
- Produces: `POST /chat` now returns `text/event-stream`. Each line-pair is either:
  - `event: node\ndata: {"node": "<name>", "data": {...}}\n\n`
  - `event: result\ndata: {"reply": str, "leads": list|None, "paused": bool, "gate_message": str|None}\n\n`
    (exactly one `result` event per request, always last)

- [ ] **Step 1: Write the failing test for the node-event sequence (enrich_leads path)**

Replace the two existing `/chat` tests in `tests/test_server.py` (search for
`test_chat_find_intent_saves_leads_and_pauses` and
`test_chat_enrich_after_gate_updates_db`) with SSE-aware versions. First, add this
helper near the top of the file (after the existing imports):

```python
def _parse_sse(text: str) -> list[dict]:
    """Test helper: parse raw SSE text into a list of {"event": ..., "data": ...}."""
    import json as _json
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = _json.loads(line[len("data:"):].strip())
        events.append({"event": event_type, "data": data})
    return events
```

Then replace the two chat tests with:

```python
def test_chat_find_intent_streams_node_events_and_pauses(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads4.db"))
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test_agent4.db"))
    import importlib
    import graph
    importlib.reload(graph)
    from graph import Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=(
        '[{"first_name": "Jane", "last_name": "Doe", "company": "Acme", "domain": "acme.com"}]'
    ))

    with patch("graph.llm", fake_llm):
        import server
        importlib.reload(server)

        client = TestClient(server.app)
        with client.stream(
            "POST", "/chat", json={"message": "find fintech VPs", "thread_id": "t1"}
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    node_events = [e for e in events if e["event"] == "node"]
    result_events = [e for e in events if e["event"] == "result"]

    assert [e["data"]["node"] for e in node_events] == ["intent_node", "find_node"]
    assert node_events[0]["data"]["data"]["intent"] == "find_leads"

    assert len(result_events) == 1
    result = result_events[0]["data"]
    assert result["paused"] is True
    assert result["leads"][0]["first_name"] == "Jane"

    saved = client.get("/leads").json()
    assert len(saved) == 1
    assert saved[0]["first_name"] == "Jane"


def test_chat_enrich_after_gate_streams_and_updates_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads5.db"))
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test_agent5.db"))
    import importlib
    import graph
    importlib.reload(graph)
    from graph import Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=(
        '[{"first_name": "Jane", "last_name": "Doe", "company": "Acme", "domain": "acme.com"}]'
    ))

    with patch("graph.llm", fake_llm), patch("graph.requests.get") as mock_get:
        mock_get.return_value = _verifier_resp("deliverable", "jane.doe@acme.com")
        import server
        importlib.reload(server)

        client = TestClient(server.app)
        with client.stream(
            "POST", "/chat", json={"message": "find fintech VPs", "thread_id": "t2"}
        ) as resp:
            "".join(resp.iter_text())

        with client.stream(
            "POST", "/chat", json={"message": "enrich", "thread_id": "t2"}
        ) as resp:
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    node_events = [e["data"]["node"] for e in events if e["event"] == "node"]
    assert node_events == ["enrich_node", "apollo_phone_node"]

    result = next(e["data"] for e in events if e["event"] == "result")
    assert result["paused"] is False

    saved = client.get("/leads").json()
    assert saved[0]["email"] == "jane.doe@acme.com"
    assert saved[0]["status"] == "verified"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — current `/chat` returns a plain JSON body, not an SSE stream, so
`resp.iter_text()` won't contain `event:`/`data:` lines and `_parse_sse` will produce
no matching events.

- [ ] **Step 3: Rewrite the `/chat` handler in `server.py`**

Replace the imports at the top of `server.py`:

```python
import csv
import io
import json
import os
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from db import init_db, list_leads, insert_csv_rows, get_leads_by_ids, update_lead_enrichment, upsert_lead
from graph import enrich_node, apollo_phone_node
from graph import app as compiled_graph
```

Replace the `_is_paused` helper and the `chat` function (everything from
`def _is_paused` to the end of the file) with:

```python
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _save_result_to_db(values: dict) -> None:
    for lead in values.get("leads", []):
        upsert_lead(db_conn, {**lead, "source": "chat"})
    for lead in values.get("enriched", []):
        lead_id = upsert_lead(db_conn, {**lead, "source": "chat"})
        update_lead_enrichment(
            db_conn, lead_id, lead.get("email"), lead.get("status"),
            lead.get("phone"), lead.get("phone_status"),
        )


def _build_result(config: dict) -> dict:
    snapshot = compiled_graph.get_state(config)
    values = snapshot.values
    _save_result_to_db(values)

    if snapshot.next:
        interrupt_obj = snapshot.tasks[0].interrupts[0]
        payload = interrupt_obj.value
        return {
            "reply": payload["message"],
            "leads": payload["leads"],
            "paused": True,
            "gate_message": payload["message"],
        }

    return {
        "reply": f"Done. Intent: {values.get('intent')}",
        "leads": values.get("enriched") or values.get("leads"),
        "paused": False,
        "gate_message": None,
    }


def _stream_chat(input_or_command, config: dict):
    for update in compiled_graph.stream(input_or_command, config, stream_mode="updates"):
        node_name = next(iter(update))
        if node_name == "__interrupt__":
            continue
        yield _sse("node", {"node": node_name, "data": update[node_name]})

    yield _sse("result", _build_result(config))


@app.post("/chat")
def chat(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    snapshot = compiled_graph.get_state(config)

    if snapshot.next:
        input_or_command = Command(resume=req.message)
    else:
        input_or_command = {
            "messages": [HumanMessage(content=req.message)], "intent": "",
            "leads": [], "enriched": [], "gate_decision": "",
        }

    return StreamingResponse(
        _stream_chat(input_or_command, config), media_type="text/event-stream"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_server.py -v`
Expected: PASS (both new `/chat` tests, plus the 3 unrelated `/leads*` tests still
pass unmodified).

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -v`
Expected: all tests pass (26 previously-passing + the 2 rewritten `/chat` tests).

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: stream /chat as SSE node/result events"
```

---

## Task 2: SSE line parser (frontend, pure function)

**Files:**
- Create: `frontend/src/sse.js`
- Test: `frontend/src/sse.test.js`

**Interfaces:**
- Produces: `parseSseChunk(buffer: string) -> { events: {event: string, data: any}[], remainder: string }`.
  Call this incrementally as chunks of SSE text arrive; pass the previous call's
  `remainder` back in as the prefix of the next chunk. Returns any fully-parsed
  `event:`/`data:` blocks found so far, plus the leftover incomplete text
  (`remainder`) to prepend to the next chunk.

- [ ] **Step 1: Write the failing test**

`frontend/src/sse.test.js`:
```javascript
import { describe, it, expect } from 'vitest'
import { parseSseChunk } from './sse'

describe('parseSseChunk', () => {
  it('parses a single complete event', () => {
    const text = 'event: node\ndata: {"node":"intent_node"}\n\n'
    const { events, remainder } = parseSseChunk(text)
    expect(events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
    expect(remainder).toBe('')
  })

  it('parses multiple events in one chunk', () => {
    const text =
      'event: node\ndata: {"node":"intent_node"}\n\n' +
      'event: node\ndata: {"node":"find_node"}\n\n'
    const { events } = parseSseChunk(text)
    expect(events.map((e) => e.data.node)).toEqual(['intent_node', 'find_node'])
  })

  it('holds back an incomplete trailing event as remainder', () => {
    const text = 'event: node\ndata: {"node":"intent_node"}\n\nevent: node\ndata: {"nod'
    const { events, remainder } = parseSseChunk(text)
    expect(events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
    expect(remainder).toBe('event: node\ndata: {"nod')
  })

  it('completes a split event when the remainder is prepended to the next chunk', () => {
    const first = parseSseChunk('event: node\ndata: {"nod')
    const second = parseSseChunk(first.remainder + 'e":"intent_node"}\n\n')
    expect(second.events).toEqual([{ event: 'node', data: { node: 'intent_node' } }])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test` (in `frontend/`)
Expected: FAIL — `sse.js` does not exist.

- [ ] **Step 3: Write `frontend/src/sse.js`**

```javascript
export function parseSseChunk(buffer) {
  const events = []
  const blocks = buffer.split('\n\n')
  // The last element is either '' (buffer ended cleanly on a blank line) or an
  // incomplete trailing block — either way, it is not yet a complete event.
  const remainder = blocks.pop()

  for (const block of blocks) {
    if (!block.trim()) continue
    let eventType = null
    let data = null
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventType = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        data = JSON.parse(line.slice('data:'.length).trim())
      }
    }
    if (eventType) events.push({ event: eventType, data })
  }

  return { events, remainder }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/sse.js src/sse.test.js
git commit -m "feat: add pure SSE line-parser"
```

---

## Task 3: `sendChat` reads the SSE stream

**Files:**
- Modify: `frontend/src/api.js`

**Interfaces:**
- Consumes: `parseSseChunk` from `./sse.js`.
- Produces: `sendChat(message: string, threadId: string, onNodeEvent?: (data) => void) -> Promise<resultData>`.
  `onNodeEvent` is called once per `node` event with that event's `data` field
  (`{node, data}`). The returned promise resolves with the `result` event's `data`
  field once it arrives.

- [ ] **Step 1: Write `sendChat`'s new implementation**

No isolated unit test for this one — it wraps the browser's streaming `fetch`, which
`sse.js` (Task 2) already covers in isolation, and `GraphPanel`/`Chat` component tests
(Tasks 4-5) exercise it through mocking. Replace `sendChat` in `frontend/src/api.js`:

```javascript
import { parseSseChunk } from './sse'

export async function sendChat(message, threadId, onNodeEvent) {
  const resp = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
  })

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, remainder } = parseSseChunk(buffer)
    buffer = remainder
    for (const evt of events) {
      if (evt.event === 'node' && onNodeEvent) onNodeEvent(evt.data)
      if (evt.event === 'result') result = evt.data
    }
  }

  return result
}
```

Add the import line (`import { parseSseChunk } from './sse'`) at the top of the file
alongside the existing `BASE_URL` constant.

- [ ] **Step 2: Manually sanity-check the module loads**

Run: `npm run build` (in `frontend/`)
Expected: builds with no errors (confirms no syntax/import mistakes before wiring it
into components in the next tasks).

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/api.js
git commit -m "feat: sendChat reads the /chat SSE stream"
```

---

## Task 4: `GraphPanel` component

**Files:**
- Create: `frontend/src/pages/GraphPanel.jsx`
- Create: `frontend/src/pages/GraphPanel.css`
- Test: `frontend/src/pages/GraphPanel.test.jsx`

**Interfaces:**
- Produces: `GraphPanel` (default export), props: `{ path: {node: string, status: 'pending'|'current'|'completed'}[] }`.
  The parent (`Chat.jsx`, Task 5) owns the `path` array's state and updates it; this
  component is purely presentational.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/GraphPanel.test.jsx`:
```jsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import GraphPanel from './GraphPanel'

describe('GraphPanel', () => {
  it('renders all five node names', () => {
    render(<GraphPanel path={[]} />)
    expect(screen.getByText('intent_node')).toBeInTheDocument()
    expect(screen.getByText('find_node')).toBeInTheDocument()
    expect(screen.getByText('human_gate')).toBeInTheDocument()
    expect(screen.getByText('enrich_node')).toBeInTheDocument()
    expect(screen.getByText('apollo_phone_node')).toBeInTheDocument()
  })

  it('marks nodes completed and current based on path', () => {
    render(<GraphPanel path={[
      { node: 'intent_node', status: 'completed' },
      { node: 'find_node', status: 'current' },
    ]} />)
    expect(screen.getByText('intent_node').closest('.graph-node')).toHaveClass('completed')
    expect(screen.getByText('find_node').closest('.graph-node')).toHaveClass('current')
    expect(screen.getByText('human_gate').closest('.graph-node')).toHaveClass('pending')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `GraphPanel.jsx` does not exist.

- [ ] **Step 3: Write `frontend/src/pages/GraphPanel.jsx`**

```jsx
import './GraphPanel.css'

const NODE_NAMES = ['intent_node', 'find_node', 'human_gate', 'enrich_node', 'apollo_phone_node']

function statusFor(path, nodeName) {
  const entry = path.find((p) => p.node === nodeName)
  return entry ? entry.status : 'pending'
}

export default function GraphPanel({ path }) {
  return (
    <div className="graph-panel">
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'intent_node')}`}>intent_node</div>
      </div>
      <div className="graph-row graph-row-fork">
        <div className={`graph-node ${statusFor(path, 'find_node')}`}>find_node</div>
        <div className={`graph-node ${statusFor(path, 'enrich_node')}`}>enrich_node</div>
      </div>
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'human_gate')}`}>human_gate</div>
      </div>
      <div className="graph-row">
        <div className={`graph-node ${statusFor(path, 'apollo_phone_node')}`}>apollo_phone_node</div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Write `frontend/src/pages/GraphPanel.css`**

```css
.graph-panel {
  max-width: 480px;
  margin: 12px auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  font-family: var(--sans);
  font-size: 12px;
}

.graph-row {
  display: flex;
  gap: 16px;
}

.graph-node {
  border: 1.5px solid #d1d5db;
  color: #9ca3af;
  border-radius: 8px;
  padding: 6px 12px;
  transition: all 0.2s ease;
}

.graph-node.current {
  border-color: var(--crm-accent, #2563eb);
  color: var(--crm-accent, #2563eb);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2);
  animation: graph-node-pulse 1.4s infinite ease-in-out;
}

.graph-node.completed {
  border-color: #16a34a;
  color: #16a34a;
}

@keyframes graph-node-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2); }
  50% { box-shadow: 0 0 0 6px rgba(37, 99, 235, 0.08); }
}

@media (prefers-reduced-motion: reduce) {
  .graph-node.current {
    animation: none;
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/GraphPanel.jsx src/pages/GraphPanel.css src/pages/GraphPanel.test.jsx
git commit -m "feat: add GraphPanel node-diagram component"
```

---

## Task 5: Wire `GraphPanel` into `Chat.jsx`

**Files:**
- Modify: `frontend/src/pages/Chat.jsx`
- Modify: `frontend/src/pages/Chat.test.jsx`

**Interfaces:**
- Consumes: `sendChat(message, threadId, onNodeEvent)` (Task 3), `GraphPanel` (Task 4).
- Produces: `Chat.jsx` maintains a `path` state array
  (`{node, status}[]`) passed to `GraphPanel`, reset at the start of each `send()` call
  and updated as `node` events arrive.

- [ ] **Step 1: Update the existing Chat tests for the new `sendChat` signature**

The mocks in `frontend/src/pages/Chat.test.jsx` use `mockResolvedValue`, which works
regardless of how many arguments `sendChat` is called with, so no change is strictly
required for the two existing tests to keep passing. Add one new test asserting the
panel resets and animates:

```jsx
it('shows the graph panel and marks the current node from node events', async () => {
  api.sendChat.mockImplementation(async (message, threadId, onNodeEvent) => {
    onNodeEvent({ node: 'intent_node', data: { intent: 'find_leads' } })
    onNodeEvent({ node: 'find_node', data: {} })
    return { reply: 'Found 1 leads.', leads: [{ first_name: 'Jane' }], paused: true, gate_message: 'x' }
  })

  render(<Chat />)
  fireEvent.change(screen.getByPlaceholderText(/message/i), { target: { value: 'find VPs' } })
  fireEvent.click(screen.getByText(/send/i))

  await waitFor(() =>
    expect(screen.getByText('find_node').closest('.graph-node')).toHaveClass('completed')
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `Chat.jsx` doesn't render `GraphPanel` yet, so `.graph-node` doesn't
exist.

- [ ] **Step 3: Update `frontend/src/pages/Chat.jsx`**

Add the import at the top:
```javascript
import GraphPanel from './GraphPanel'
```

Add a `path` state next to the existing state declarations:
```javascript
const [path, setPath] = useState([])
```

Replace the `send` function's body with a version that resets `path` and updates it
via the `onNodeEvent` callback:

```javascript
async function send(text) {
  if (!text.trim() || sending) return
  setSending(true)
  setPath([])
  setMessages((m) => [...m, { role: 'user', text }])
  try {
    const result = await sendChat(text, threadId, (evt) => {
      setPath((prev) => {
        const next = prev.map((p) => ({ ...p, status: 'completed' }))
        const already = next.find((p) => p.node === evt.node)
        if (already) {
          already.status = 'completed'
        } else {
          next.push({ node: evt.node, status: 'completed' })
        }

        if (evt.node === 'intent_node') {
          const branch = evt.data.intent === 'enrich_leads' ? 'enrich_node' : 'find_node'
          next.push({ node: branch, status: 'current' })
        } else if (evt.node === 'find_node') {
          next.push({ node: 'human_gate', status: 'current' })
        } else if (evt.node === 'human_gate') {
          next.push({ node: 'enrich_node', status: 'current' })
        } else if (evt.node === 'enrich_node') {
          next.push({ node: 'apollo_phone_node', status: 'current' })
        }
        return next
      })
    })
    setMessages((m) => [...m, { role: 'agent', text: result.reply }])
    setPending(result.paused ? result : null)
  } finally {
    setSending(false)
  }
}
```

Render the panel just above the composer (inside `chat-scroll`, after the message
thread, or as its own row below `chat-thread`) — add this line right before the
closing `</div>` of `chat-scroll`:
```jsx
{path.length > 0 && <GraphPanel path={path} />}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test`
Expected: PASS (all Chat tests + the new one).

- [ ] **Step 5: Run the full frontend suite**

Run: `npm test` (no filter)
Expected: all tests pass (sse.js, GraphPanel, LeadsDatabase, Chat).

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/Chat.jsx src/pages/Chat.test.jsx
git commit -m "feat: animate GraphPanel from live /chat node events"
```

---

## Task 6: Manual end-to-end smoke test (optional, no automated test)

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
2. Watch the panel: `intent_node` should complete almost immediately, then
   `find_node` lights up as current while the web search runs, then completes,
   then `human_gate` lights up as current.
3. Click "Enrich"; confirm `enrich_node` then `apollo_phone_node` animate in turn.
4. Confirm the panel freezes on the full completed path, and sending a new message
   resets it and animates fresh.

- [ ] **Step 4: Commit any fixes discovered during the smoke test**

---

## Self-Review

**Spec coverage:**
- SSE stream architecture (`node`/`result` events, `stream_mode="updates"`) → Task 1. ✅
- Reusing `get_state()`-based pause detection instead of parsing interrupt shape → Task 1 (`_build_result`). ✅
- `intent_node` event carries `data.intent` for fork resolution → Task 1 (event payload) + Task 5 (`send`'s branch logic). ✅
- Frontend can't use `EventSource` (POST body) → Task 3 (`fetch()` + `ReadableStream`). ✅
- Node-graph panel matching the real graph shape → Task 4. ✅
- Optimistic highlight (next node lit before its own event arrives) → Task 5's `send` logic marks the *next* node `current` immediately upon the *previous* node's event. ✅
- Freeze-on-complete / reset-on-next-message → Task 5 (`setPath([])` at the start of `send`; nothing marks the final node's successor `current` once the graph ends). ✅
- Testing (backend SSE sequence, frontend pure-parser tests, component tests) → Tasks 1, 2, 4, 5. ✅
- Manual smoke test → Task 6. ✅

**Not implemented (explicitly out of scope per spec section 5, not silent gaps):**
- 60-second client-side disconnect timeout and a dedicated `error` SSE event type are
  named in the spec as acceptable first-version degradations, not required for this
  plan's completion.

**Placeholder scan:** No TBD/TODO. The one deliberately-deferred item (timeout/error
event) is called out above with its spec citation, not left as a silent gap.

**Type consistency:** `sendChat(message, threadId, onNodeEvent)` in Task 3 matches the
call site in Task 5. `GraphPanel`'s `path` prop shape (`{node, status}[]`) matches what
`Chat.jsx`'s `send()` builds via `setPath` and what `GraphPanel.test.jsx` passes
directly. The SSE event field names (`event`, `data`) used by `parseSseChunk` (Task 2)
match what `sendChat` (Task 3) destructures (`evt.event`, `evt.data`), which match what
`server.py`'s `_sse()` helper (Task 1) writes on the wire.
