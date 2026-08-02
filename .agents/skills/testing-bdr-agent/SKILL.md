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

## Notification settings
Stored as one JSON blob in the new `settings` table (`select value from settings`). Secrets
(`slack_webhook_url`, `smtp_password`) are redacted by `GET /settings/notifications` into
`*_set` booleans; a blank field on PUT keeps the stored value. Verify secrecy against the raw
API/DB, not the UI alone — error strings from providers may still echo secrets back.

## Devin Secrets Needed
- `ANTHROPIC_API_KEY`, `HUNTER_API_KEY` — required only for live agent runs / enrichment.
- A real Slack incoming webhook and SMTP creds if you need to prove notification delivery.
