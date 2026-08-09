# AGENTS.md

Guidance for AI agents and contributors working in this repo. For full setup/run/env
instructions see [`README.md`](./README.md); for a node-by-node walkthrough see
[`01-how-it-works (1).md`](./01-how-it-works%20\(1\).md).

## What this is

A BDR (sales prospecting) agent: a LangGraph state machine behind a FastAPI backend and a
React/Vite UI. A chat message runs the graph; leads are persisted to SQLite and shown in the
Leads Database tab.

## Layout

- `server.py` — FastAPI app. `/chat` streams graph progress as SSE; `/leads*` CRUD + enrich;
  `/settings*`, `/usage`.
- `graph.py` — builds/compiles the LangGraph graph with a SQLite checkpointer (`agent.db`).
- `state.py` — `AgentState` TypedDict. `messages` uses the `add_messages` reducer (it
  **accumulates** within a thread — see Gotchas).
- `routing.py`, `nodes/` — one file per graph node.
- `db.py` — `leads.db` access (leads + `settings` table).
- `constants.py` — `llm` (general) and `search_llm` (web-search) model handles.
- `frontend/` — Vite app; `src/pages/Chat.jsx` drives the chat + human-gate UI, `src/api.js`
  is the SSE client.
- `tests/` — pytest (backend); `frontend/src/**/*.test.jsx` — vitest.
- `.agents/skills/testing-bdr-agent/` — how to run the app locally for E2E testing.

## Graph flow

```
intent_node ─┬─(find_leads)→ find → dedupe → research → profile → score → human_gate
             ├─(enrich_leads)──────────────────────────────────────────→ enrich_node
             └─(clarify)→ END
human_gate ─(enrich/draft)→ enrich_node ─┬→ draft_node → notify_node → END
           └─(done)→ END                 └→ notify_node → END
```

`human_gate` interrupts the run; the UI resumes it with `Command(resume=<decision>)`.

## Commands

```bash
.venv/bin/uvicorn server:app --reload        # backend :8000
(cd frontend && npm run dev)                  # frontend :5173

.venv/bin/python -m pytest -q                 # backend tests (run with NO real keys)
(cd frontend && npm test && npm run lint)     # frontend tests + oxlint
python graph.py "find VPs of Sales at fintech"  # run the graph headless
```

Always run the relevant test/lint commands before opening a PR.

## Conventions

- Keep changes focused; match existing style; no comments unless the code is non-obvious.
- Node functions take `state` (+ optional injected `llm`) and return a partial state dict.
  Preserve input lead order.
- Per-lead network/LLM work in `research`/`profile`/`enrich` runs through
  `nodes/concurrency.py#parallel_map` (order-preserving, bounded by `ENRICH_MAX_WORKERS`,
  default 8).
- Never commit `.env` (gitignored). Tests must not hit real APIs — `tests/conftest.py` unsets
  provider keys so a local `.env` can't leak into the suite. Don't weaken it.

## Gotchas

- **Thread = one search.** `messages` accumulates within a `thread_id`, so reusing a thread
  across independent searches bleeds prior context into `intent_node`/`find_node`. The UI
  starts a fresh `thread_id` per new search and reuses it only for human-gate replies. Keep
  that invariant.
- **Chat errors must surface.** `api.js` throws on unreachable/non-200/empty-stream; `Chat.jsx`
  catches and renders an error bubble while keeping the composer and any pending gate usable.
  Don't swallow these.
- `agent.db`/`leads.db` are created on first run and gitignored.
