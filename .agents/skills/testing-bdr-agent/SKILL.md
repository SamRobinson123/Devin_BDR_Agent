---
name: testing-bdr-agent
description: How to run and test the Devin-BDR-Agent app locally (FastAPI + Vite) without live LLM/Hunter API keys.
---

# Testing the BDR Agent locally

## Bring the app up
```bash
cd <repo>
bash scripts/setup.sh          # fresh clone only: venv + pip + npm install + cp .env.example .env (~2-3 min)
printf 'ANTHROPIC_API_KEY=dummy\nHUNTER_API_KEY=dummy\n' > .env   # import-time only; no live calls needed for UI work
.venv/bin/uvicorn server:app --port 8000 &
cd frontend && npm run dev &                                      # http://localhost:5173
```
To test the documented from-scratch path, clone the branch into a new dir
(`git clone -b <branch> <repo> /home/ubuntu/clean-clone`) so no existing `.venv`/`node_modules` is reused.
`leads.db`/`agent.db` (+ `-wal`/`-shm`) are created on first backend start and are gitignored, so
`git status` should stay clean; a fresh clone renders the "0 leads tracked" empty state.

Process-management gotchas on this box: `pkill -f vite` / `pkill -f uvicorn` also matches the exec
tool's own shell and kills it (exit -1). Start dev servers with
`setsid nohup npm run dev > /tmp/vite.log 2>&1 < /dev/null &` and prefer killing by port/PID.
Dummy keys are enough for the Settings tab, the Leads Database table, and anything that does not
run the LangGraph agent. Real agent runs (Chat, graph nodes like `profile_node`/`notify_node`/`phone_node`)
need genuine keys — see Devin Secrets Needed.

## Seeding leads without the agent
`leads.db` is plain sqlite; `db.upsert_lead(conn, dict)` writes profile fields. `prior_companies`,
`talking_points`, `profile_sources` are list fields stored as JSON text and decoded by the API —
pass real Python lists, not strings, so the UI list rendering is exercised.
```python
import db; c = db.init_db('leads.db')
i = db.upsert_lead(c, {'first_name':'Ada','last_name':'Lovelace','company':'X','domain':'x.io','source':'seed'})
db.upsert_lead(c, {'first_name':'Ada','last_name':'Lovelace','company':'X','domain':'x.io',
                   'title':'VP Eng','linkedin_url':'https://www.linkedin.com/in/example',
                   'talking_points':['a','b'],'prior_companies':['P','Q'],
                   'profile_sources':['https://x.io/team'],'person_summary':'…'})
```
A lead only shows the select checkbox when `status == 'pending'`.

## Driving a Chat run without real LLM keys (stub SSE gateway)
`frontend/src/api.js` uses `BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'`,
so you can either point the UI at another backend via `frontend/.env`
(`VITE_API_BASE_URL=http://localhost:8001`, requires a Vite restart — it is not hot-reloaded), or keep
the default and put a stub on `:8000` while the real server moves to `:8001`. CORS `allow_origins` in
`server.py` is keyed on the UI origin (`http://localhost:5173`) only, so moving the *backend* port needs
no CORS change; moving the UI port does. Write a throwaway FastAPI app that proxies everything to `:8001` (httpx) except `POST /chat`,
which streams canned frames; delete it when you're done (do not commit it).
```python
def sse(event, data): return f"event: {event}\ndata: {json.dumps(data)}\n\n"
# yield sse("node", {"node": "find_node", "data": {"leads": [...]}})  # sleep ~3s between frames
# ... intent_node -> find_node -> dedupe_node -> research_node -> profile_node -> score_node
# finally: yield sse("result", {"reply": "...", "leads": [...], "paused": False})
```
Notes that matter:
- `Chat.jsx` derives the *current* node from `NEXT_NODE`, so the graph halo/animated edge only appears
  while frames are still arriving — space frames ~3s apart or you will never screenshot the animation.
- `RunActivity` reads `data.leads` / `data.enriched`, plus `data.skipped` for `dedupe_node` and
  `data.intent` for `intent_node`. Only `find_node` results are expanded by default.
- `/chat` traffic through the stub never reaches `server.py`, so the mid-run `_save_result_to_db`
  persistence is NOT exercised this way — seed `leads.db` directly to test the Leads tab's 5s polling.
- Pressing Enter in the composer submits (Shift+Enter newlines) — use Shift+Enter to test autogrow.

## Faking Hunter / Anthropic-billing responses (Usage & Spend tab)
`usage.py` holds the outbound URLs as module constants, so you can redirect them without touching
repo code: run a small fake-provider FastAPI app on another port, then serve the real app through a
throwaway wrapper that rebinds the constants *before* importing `server`. Keep both files untracked.
```python
# stub_server.py — run with: uvicorn stub_server:app --port 8000
import usage
usage.HUNTER_ACCOUNT_URL = "http://localhost:8002/v2/account"
usage.ANTHROPIC_COST_URL = "http://localhost:8002/v1/organizations/cost_report"
import server
app = server.app
```
Why this beats monkeypatching `requests`: the real header/401/pagination/cents→USD code still runs.
- Leave `HUNTER_UPGRADE_URL`, `ANTHROPIC_USAGE_URL`, `ANTHROPIC_ADMIN_KEYS_URL` unpatched so the UI's
  outbound link targets can still be verified against the real constants.
- Tune the fake Hunter quotas to hit every meter tone in one screenshot — remaining ≤5% is red,
  ≤20% amber, else default (e.g. 970/1000, 850/1000, 200/1000).
- Anthropic `cost_report` amounts are **cents**; have the fake return a distinctive total so the
  conversion is falsifiable (2185c must render as `$21.85`).
- Prove labelling honesty by saving a key the fake rejects first: the pill must stay
  "Estimated locally". A stub that 401s anything not starting with `sk-ant-admin` makes this easy.
- Hunter states are driven by the backend env, so each needs a restart: `HUNTER_API_KEY=badkey`
  (401 path) and removing the var from both the environment and `.env` (unconfigured path).
- Admin-key/budget writes land in the `settings` table, not a file. Reset a run's state with
  `db.set_setting(conn, usage.SETTINGS_KEY, {'monthly_budget_usd': 0.0, 'anthropic_admin_key': ''})` —
  a blank secret on PUT is ignored, so you cannot clear the key through the UI.

## Seeding the usage ledger
`usage_events` in `leads.db` backs the estimated Claude figures. Price rows through the real
`usage.token_cost(...)` so the UI total is reproducible. Seed a mix of providers: the Claude estimate
(`estimated.month`/`daily`/`by_model`) is scoped to `provider='anthropic'`, while the "Calls this
month" table is intentionally unfiltered — seeding only Anthropic rows would make a provider-filter
regression invisible. Verify `/usage` in the shell before the browser: "Priced from N recorded calls"
must equal `llm + web_search` only, and `by_model` must contain no `null`/`unknown` row.
Historically the pytest suite wrote into the repo's real `leads.db`; if row counts drift after a test
run, check that `tests/conftest.py` still redirects `LEADS_DB_PATH` and resets `usage._ledger`.
## Notification settings
Stored as one JSON blob in the new `settings` table (`select value from settings`). Secrets
(`slack_webhook_url`, `smtp_password`) are redacted by `GET /settings/notifications` into
`*_set` booleans; a blank field on PUT keeps the stored value. Verify secrecy against the raw
API/DB, not the UI alone — error strings from providers may still echo secrets back.

## Devin Secrets Needed
- `ANTHROPIC_API_KEY`, `HUNTER_API_KEY` — required only for live agent runs / enrichment.
- A real Slack incoming webhook and SMTP creds if you need to prove notification delivery.

## Testing phone enrichment under provider rate limits
Non-obvious gotchas when verifying `phone_node` / Prospeo:
- **`phone_node` short-circuits** when a lead already has a valid phone: `_find_phone` returns
  `phone_source=web_search` without calling the provider. So a normal Chat run may not exercise
  Prospeo for every lead. To force real sequential Prospeo calls (e.g. to reproduce the batch
  rate-limit path), clear `phone`/`phone_status`/`phone_source`/`phone_confidence` and set
  `status='pending'` directly in `leads.db`, then use **Enrich Selected** in the Leads Database
  tab (`POST /leads/enrich` -> `enrich_node` + `phone_node`).
- Prospeo's free/low tiers rate-limit to ~1 req/s and answer a burst with **429 "Rate limit
  exceeded"** (occasionally a misleading 400 `INVALID_API_KEY`). `nodes/phone._send()` retries
  429/5xx with backoff, but the retry is **silent** — only a *final* failure logs
  `Phone lookup failed …`. Verify the fix by outcome (`phone_source=prospeo`, `phone_status=found`,
  no ERROR lines), not by looking for a 429 in the log.
- The human gate is driven by **buttons** (Enrich / Enrich + Draft / Done) in the UI, not by
  typing "enrich" into the composer.
- The pytest suite is hermetic: `tests/conftest.py` unsets provider env vars, so a live `.env`
  will not make unit tests hit real APIs. Live end-to-end checks must go through the running app.
