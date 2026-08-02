# Live Graph Visualization — Design Spec

**Date:** 2026-08-02
**Status:** Approved design, pre-implementation

---

## 1. Purpose

The Chat page currently gives no feedback while a `/chat` request is in flight beyond
a generic "thinking" dots indicator (added in a prior pass). This adds a live panel
below the chat thread that animates the BDR agent's actual progress through
`graph.py`'s nodes (`intent_node` → `find_node`/`enrich_node` fork → `human_gate` →
shared `enrich_node` → `apollo_phone_node`) as it happens, so the user can see what
the agent is doing rather than staring at a blank wait.

Out of scope: showing token-by-token LLM output (that's a separate future feature),
persisting graph-run history for replay, and visualizing the `clarify` intent branch
distinctly (it's a short-circuit to `END`, nothing to animate).

## 2. Architecture

```
POST /chat (text/event-stream)
  for update in compiled_graph.stream(input_or_Command, config, stream_mode="updates"):
      node_name = next(iter(update))          # skip the "__interrupt__" pseudo-key
      yield SSE "node" event: {"node": node_name, "data": update[node_name]}

  # after the stream loop ends, reuse existing pause-detection logic
  snapshot = compiled_graph.get_state(config)
  yield SSE "result" event: {reply, leads, paused, gate_message}   # same shape as today
```

`stream_mode="updates"` yields one dict per completed node, keyed by that node's name
(confirmed via LangGraph's own docs). The `"__interrupt__"` key that can appear in that
stream is NOT relied on to detect the pause — instead, after the loop ends, the
existing `get_state(config)` + `snapshot.next` check (already used by today's
`_is_paused` helper) determines pause state and builds the same `{reply, leads, paused,
gate_message}` result contract the Chat page already consumes. This reuses
already-tested logic instead of depending on an SSE interrupt-chunk shape.

**Frontend transport:** the native `EventSource` API only supports GET requests, and
`/chat` needs a POST body (`message`, `thread_id`). `sendChat` in `api.js` switches to
`fetch()` + reading `response.body` as a stream, splitting the raw text on the SSE
`event:`/`data:` line format.

## 3. Node-graph panel (`GraphPanel.jsx`)

Renders the graph shape as a small fixed diagram (mirrors the shape in
`docs/superpowers/specs/2026-07-31-bdr-agent-graph-design.md` section 3):

```
                intent_node
                 /       \
           find_node   enrich_node
               |             ^
          human_gate ────────┘
               |
          apollo_phone_node
```

Each node box has 3 visual states:
- **not-yet-reached** — gray outline, gray text
- **current** — blue outline + pulse animation (per the "optimistic highlight" choice:
  lit as soon as the *previous* node's completion event arrives, i.e. before its own
  event confirms it finished)
- **completed** — green outline + checkmark

On the stream's `result` event, the last node in the actual path is marked completed
and the panel freezes showing the full path taken. It stays frozen until the next
message is sent, at which point all nodes reset to not-yet-reached before the new
run's events start arriving.

## 4. Data flow

1. User sends a message → `Chat.jsx` calls `sendChat`, which opens the SSE stream and
   resets `GraphPanel`'s state to a fresh run.
2. Each `node` event → `GraphPanel` marks that node `completed`, then decides the next
   `current` node: for every node except `intent_node` there's exactly one fixed
   successor in the diagram. For `intent_node` specifically, the event's `data.intent`
   field (`"find_leads"` / `"enrich_leads"` / `"clarify"`) picks the branch — this is
   why the `node` event carries the node's update payload, not just its name.
3. `result` event → `Chat.jsx` processes `reply`/`leads`/`paused`/`gate_message`
   exactly as it does today (no change to that logic); `GraphPanel` marks the last
   node `completed` and freezes.

## 5. Error handling

- **Stream disconnects mid-run:** a client-side 60-second no-events timeout flips the
  panel to a "connection lost — try again" state instead of hanging on a pulsing node
  forever.
- **Malformed/partial SSE lines:** the parser buffers incomplete lines across chunk
  boundaries (a normal occurrence in streaming, not an error) and only parses once a
  full `event:`/`data:` pair plus blank-line terminator has arrived; unparseable
  fragments are skipped rather than throwing.
- **Backend exceptions mid-stream:** if a node raises before yielding its update, the
  SSE stream ends without a `result` event — this hits the same 60-second timeout path
  on the frontend, which is an acceptable degradation for a first version (a dedicated
  `error` SSE event type is future work, not required now).

## 6. Testing

- Backend: a test using FastAPI `TestClient`'s streaming support, mocking `graph.llm`
  and `requests` as usual, asserting the `node` event sequence for an `enrich_leads`
  intent run (`intent_node` → `enrich_node` → `apollo_phone_node`) followed by one
  `result` event with `paused: false` and the expected `leads` payload.
- Frontend: a unit test for the SSE line-parsing function in isolation — given raw
  chunked text (including a line split across two chunks), returns the correctly
  parsed sequence of `{type, data}` events. Testing against a real streaming `fetch()`
  is impractical in jsdom, so the parser is extracted as a pure function and tested
  directly rather than through the component.
- One manual smoke test: watch the panel animate through a real find→gate→enrich run
  in the browser, confirm it freezes on completion and resets on the next message.

## 7. Success criteria

1. Sending a message shows the node panel animating through the actual path taken,
   not a generic spinner.
2. The panel accurately reflects the find_leads vs enrich_leads fork and the shared
   `enrich_node`/`apollo_phone_node` steps both paths pass through.
3. Existing Chat page behavior (message list, gate buttons, reply text) is unchanged
   from the user's perspective — only the panel is new.
4. A dropped connection doesn't leave the UI stuck silently forever — the 60-second
   timeout surfaces a visible state.
5. All existing backend/frontend tests continue to pass; new tests cover the SSE
   event sequence and the line-parser's edge cases (split lines, partial chunks).
