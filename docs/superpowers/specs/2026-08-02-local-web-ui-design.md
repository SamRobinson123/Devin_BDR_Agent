# Local Web UI for the BDR Agent — Design Spec

**Date:** 2026-08-02
**Status:** Approved design, pre-implementation

---

## 1. Purpose

Give the existing BDR agent graph (`graph.py`) a local web UI: a Claude-like chat page
to talk to the agent, and a leads database page that persists everything the agent
finds/enriches and lets the user upload their own lead lists for enrichment.

Today `graph.py` only runs via CLI (`python graph.py "..."`), with an in-memory
`MemorySaver` checkpointer — nothing survives a restart, and there's no way to browse
leads except printed stdout. This project adds a persistence + API + UI layer around
the existing graph without changing its node logic.

Out of scope: multi-user auth, deployment/hosting (this is a local single-user app),
Apollo/other paid phone-lookup integration (still unresolved per
`docs/superpowers/specs/2026-08-01-phone-email-enrichment-design.md`), a "refine search"
loop back to `find_node` (already out of scope in the original graph spec).

## 2. Architecture

```
React (Vite) frontend  ──HTTP/SSE──►  FastAPI backend  ──►  graph.py (existing, unchanged logic)
     Chat page                              │                     │
     Leads DB page                          └──────────────► SQLite (leads.db)
                                                              - leads table
                                                              - LangGraph checkpoints (SqliteSaver)
```

One SQLite file (`leads.db`) holds two things: a `leads` table this project owns
directly, and LangGraph's own checkpoint tables via `SqliteSaver` (replacing
`MemorySaver`), so a paused conversation (mid human-gate interrupt) survives a backend
restart. `graph.py`'s node functions (`intent_node`, `find_node`, `enrich_node`,
`apollo_phone_node`, `human_gate`, `route_*`) are unchanged — only `build_graph()`'s
checkpointer argument changes, plus a small persistence hook after `find_node` runs.

Two pages, switched via top-level tab navigation (not a persistent split view):
**Chat** and **Leads Database**.

## 3. Data model — `leads` table

```sql
CREATE TABLE leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    company TEXT,
    domain TEXT,
    email TEXT,
    status TEXT,            -- "verified" | "not_found" | "error" | "pending"
    phone TEXT,
    phone_status TEXT,       -- "found" | "not_found" | "pending"
    source TEXT NOT NULL,    -- "chat" | "csv_upload"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

One row per lead. Leads found via chat are upserted into this table as soon as
`find_node` returns them (status `"pending"` until enriched) — nothing found is lost
even if the user replies "done" at the gate. CSV-uploaded rows also start `"pending"`;
uniqueness for upsert purposes is `(first_name, last_name, domain)`.

## 4. Backend API (FastAPI)

The frontend generates one `thread_id` (a UUID) per browser session on first load,
stores it in `localStorage`, and reuses it for every `/chat` call in that session —
this is what ties a paused human-gate interrupt to the follow-up Enrich/Done click.

- **`POST /chat`** — body `{message: str, thread_id: str}`. If `thread_id` is mid-
  interrupt (tracked via a small in-memory or DB-backed map of thread_id → paused/not),
  treats `message` as the gate's resume value (`"enrich"`/`"done"`) and calls
  `app.invoke(Command(resume=message), config)`; otherwise calls
  `app.invoke({"messages": [HumanMessage(message)], ...}, config)`. After any run that
  produced `leads`, upserts them into the `leads` table before responding. Response
  shape: `{reply: str, leads: [...] | null, paused: bool, gate_message: str | null}`.
- **`GET /leads`** — returns all rows, optional `?status=` filter.
- **`POST /leads/upload`** — multipart CSV upload. Required columns: `first_name`,
  `last_name`, `domain` (`company` optional). Validates each row; malformed rows are
  rejected individually and reported back (`{inserted: N, errors: [{row, reason}]}`),
  not silently dropped. Valid rows inserted with `source="csv_upload"`,
  `status="pending"`.
- **`POST /leads/enrich`** — body `{lead_ids: [int]}`. Loads those rows, runs
  `enrich_node` then `apollo_phone_node` directly on them (as plain function calls, not
  through the compiled graph — this path never goes through `intent_node`/`find_node`/
  `human_gate` since the leads are already known), writes results back to the DB.

## 5. Frontend — Chat page

Standard chat-bubble layout: user messages right-aligned, agent left-aligned, message
input at the bottom. When `/chat` responds with `paused: true`, render an agent message
showing `gate_message` plus **Enrich** / **Done** buttons in place of free-text input
for that turn. Clicking a button POSTs to `/chat` with that button's value as `message`
under the same `thread_id`.

## 6. Frontend — Leads Database page

A table with columns: name (first + last), company, domain, email, email status,
phone, phone status. Sortable/filterable. A file-upload control for CSV import, showing
the `{inserted, errors}` result after upload. Rows with `status: "pending"` get a
checkbox + a batch **Enrich Selected** button (and a "select all pending" shortcut)
that calls `POST /leads/enrich`; the table refreshes to show updated status/email/phone
once the call returns.

## 7. Error handling

- Backend surfaces node-level statuses (`status`/`phone_status: "error"`) as-is in the
  table — `graph.py`'s existing per-lead isolation (one bad lead never breaks a batch)
  means the API layer doesn't need its own retry/isolation logic, just pass-through.
- CSV upload: missing required columns on a row → that row is reported as an error and
  skipped; the rest of the file still imports.
- `/chat` on an unknown/expired `thread_id` (e.g. server restarted mid-conversation
  before this project existed, or DB file deleted) starts a fresh conversation rather
  than erroring — `SqliteSaver` returns empty state for an unseen thread_id, which the
  graph handles the same as a first message.

## 8. Testing

- Backend: pytest + FastAPI's `TestClient`, mocking `graph.llm` and `requests` exactly
  like the existing node-level test suite — no live API calls. Cases: chat happy path,
  chat resume-after-gate, upsert-on-find behavior, CSV upload with valid + invalid rows,
  `/leads/enrich` batch call.
- Frontend: component tests for the chat gate buttons (renders buttons when paused,
  posts correct resume value) and the leads table's enrich action (calls the right
  endpoint with selected IDs).
- One manual end-to-end smoke test: upload a CSV, select rows, enrich, confirm the
  table updates — mirrors Task 9 in the original graph plan.

## 9. Success criteria

1. Chat page can run a full find→gate→enrich conversation through the browser, buttons
   working in place of the CLI's `input()`.
2. Leads found via chat appear in the database immediately, before any enrich decision.
3. CSV upload inserts valid rows as `pending` and reports per-row errors for invalid
   ones, without aborting the whole upload.
4. Selecting pending leads and clicking Enrich updates their email/phone/status once
   the `/leads/enrich` call returns and the table refetches — no real-time/websocket
   push required, a post-response refetch is sufficient.
5. Restarting the backend mid-conversation (after a `human_gate` interrupt) does not
   lose that paused state — resuming still works.
