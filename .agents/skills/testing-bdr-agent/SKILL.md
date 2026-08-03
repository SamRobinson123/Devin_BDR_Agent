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

## Notification settings
Stored as one JSON blob in the new `settings` table (`select value from settings`). Secrets
(`slack_webhook_url`, `smtp_password`) are redacted by `GET /settings/notifications` into
`*_set` booleans; a blank field on PUT keeps the stored value. Verify secrecy against the raw
API/DB, not the UI alone — error strings from providers may still echo secrets back.

## Devin Secrets Needed
- `ANTHROPIC_API_KEY`, `HUNTER_API_KEY` — required only for live agent runs / enrichment.
- A real Slack incoming webhook and SMTP creds if you need to prove notification delivery.
