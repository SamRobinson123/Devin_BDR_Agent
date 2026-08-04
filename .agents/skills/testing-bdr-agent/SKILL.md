---
name: testing-bdr-agent
description: How to run and test the Devin-BDR-Agent app locally (FastAPI + Vite) without live LLM/Hunter API keys.
---

# Testing the BDR Agent locally

## Bring the app up
```bash
cd <repo>
printf 'ANTHROPIC_API_KEY=dummy\nHUNTER_API_KEY=dummy\n' > .env   # import-time only; no live calls needed for UI work
.venv/bin/uvicorn server:app --port 8000 &
cd frontend && npm run dev &                                      # http://localhost:5173
```
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
The frontend hardcodes `BASE_URL = 'http://localhost:8000'` (`frontend/src/api.js`) — there is no env
override — so the way to fake an agent run is to put a stub on `:8000` and move the real server to
`:8001`. Write a throwaway FastAPI app that proxies everything to `:8001` (httpx) except `POST /chat`,
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
