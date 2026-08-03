# Usage & spend tracking design

## Goal
A fourth tab, next to Chat / Leads / Settings, answering two questions at a glance:

- How many Hunter email verifications (and searches) are left on the plan, and where to upgrade.
- How much the Claude API has cost this month, against an optional budget.

## What each provider actually exposes

| Provider | Endpoint | Auth | Notes |
| --- | --- | --- | --- |
| Hunter | `GET /v2/account` | the same `HUNTER_API_KEY` the agent runs on | free call, returns `plan_name`, `reset_date` and `requests.{credits,searches,verifications}.{used,available}` |
| Anthropic | `GET /v1/organizations/cost_report` | an **organisation admin key** (`sk-ant-admin…`) | the normal API key cannot read spend; amounts come back in the currency's lowest unit (cents) |

Consequence: Hunter quota is always authoritative, Claude spend is only authoritative
when the user pastes an admin key. So spend has two sources.

## Spend sources

1. **Billed** — `cost_report` grouped by description, bucketed daily since the 1st of
   the month, summed into a monthly total plus a per-model breakdown.
2. **Estimated** — a local ledger. `llm_usage.UsageRecorder` is attached to the
   `ChatAnthropic` instance in `constants.py`, so every call (including the
   structured-output ones) lands in `usage_events` with input / output / cache-read /
   cache-write token counts, priced from `usage.MODEL_PRICING` (list prices per MTok,
   longest model-name prefix wins). Server-side web search requests are recorded
   separately at $10 / 1,000.

`usage.summary()` prefers billed and falls back to estimated, tagging the response
with `source` so the UI can label the number honestly rather than implying Anthropic
confirmed it.

The same ledger also counts non-LLM calls — `nodes/enrich.py` records one
`hunter/verification` per verifier call, `nodes/phone.py` one `phone_lookup` per
provider call — which gives the "Calls this month" breakdown. Ledger writes are
best-effort: a failure there must never break a run.

## Storage

`usage_events(ts, provider, kind, model, requests, input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens, cost_usd)` in `leads.db`, created by
`init_db` so existing databases pick it up on next start. Aggregation is pushed into
SQL (`usage_grouped` by day / provider / model / kind, `usage_totals`).

## Settings

New `usage` settings blob: `anthropic_admin_key` (secret, never echoed back) and
`monthly_budget_usd`. The secret-handling that `notifications.py` already had is now
shared in `settings_store.py`.

## API

- `GET /usage` — hunter quota, billed + estimated Claude spend, budget state.
- `GET /PUT /settings/usage` — admin key (write-only) and budget.

## UI

`frontend/src/pages/Usage.jsx`, edited in the Usage tab itself rather than Settings so
billing lives in one place: spend headline with a billed/estimated pill, budget meter,
30-day bar chart, per-model table, Hunter quota meters that turn amber under 20% and
red under 5% remaining, plus links to Hunter pricing and the Anthropic console.

## Out of scope

- Per-run cost attribution in the chat transcript.
- Alerting when the budget is exceeded (the meter only shows it).
