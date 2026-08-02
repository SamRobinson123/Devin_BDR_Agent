# Prospect Intel, Phone Providers, and Notifications — Design Spec

**Date:** 2026-08-02
**Status:** Implemented
**Supersedes:** the phone half of
`docs/superpowers/specs/2026-08-01-phone-email-enrichment-design.md`

---

## 1. Purpose

Three changes:

1. **Person-level research.** Everything in the graph researched the *company*. Nothing
   researched the *person*, so `score_node` ranked a junior IC at a great-fit company
   above the actual buyer, and `draft_node` had only company facts to personalize with.
2. **Phone numbers from a real provider.** Apollo is out — too expensive for the value.
   `apollo_phone_node` is replaced by a provider-agnostic `phone_node`.
3. **Slack / email delivery.** The agent could only talk through the web UI, so a run
   finishing or a human gate opening went unnoticed unless the tab was open.

## 2. Graph

```
intent_node ─(find_leads)─► find_node ─► dedupe_node ─► research_node ─► profile_node
                                              ─► score_node ─► human_gate ─┐
            ─(enrich_leads)──────────────────────────────────────────────► enrich_node
                                        ─► phone_node ─(draft?)─► draft_node ─► notify_node
```

`profile_node` sits between `research_node` and `score_node` so its output feeds ranking.
`notify_node` is terminal, so every completed run reports once.

## 3. `profile_node`

One search-enabled Claude call per lead (unlike `research_node`, which caches per domain),
so it is budgeted: `limit=10` leads per run, and leads without a full name are skipped.

Returns, merged onto the lead: `linkedin_url`, `title`, `seniority`, `tenure`,
`prior_companies`, `person_summary`, `talking_points`, `profile_sources`. Existing lead
values win over model output. Unverifiable fields stay `null`, and `talking_points` must be
`[]` rather than invented — the same discipline `research_node` already uses.

`score_node` now receives `seniority`/`tenure`/`person_summary`/`talking_points` and is told
to weigh whether the person is plausibly the buyer. `draft_node` prefers a person-level
talking point over a company fact.

**LinkedIn scraping is deliberately not done.** It breaks their ToS and gets IPs banned;
`profile_node` reads public search results instead. Structured LinkedIn fields at volume
would need Proxycurl/Bright Data.

## 4. `phone_node`

Provider-agnostic, selected by env:

```
PHONE_PROVIDER=datagma|prospeo|none   (default none)
DATAGMA_API_KEY / PROSPEO_API_KEY
```

Both providers charge only when they return a number. Datagma is the default because its
free tier includes API access; Prospeo has better coverage but paywalls the API at $49/mo.

Lookup order per lead: existing `phone` from `find_node` → provider call keyed on
`linkedin_url` (best hit rate, which is why `profile_node` runs first) or email → fallback
on full name + company. With no provider or no key configured, the node degrades to the old
passthrough behavior: no external calls, no cost, no crash.

Writes `phone`, `phone_status` (`found`/`not_found`/`error`) and `phone_source`
(`web_search`/provider name) so a rep can tell where a number came from.

Provider responses vary by plan and change shape, so the phone is extracted by walking the
JSON for a phone-shaped string under a phone-ish key rather than a fixed path.

## 5. Notifications

Config lives in a new `settings` table in `leads.db` (key `notifications`), edited from a
new **Settings** tab. Secrets (`slack_webhook_url`, `smtp_password`) are never returned to
the browser — the API returns `*_set` booleans, and submitting a blank secret keeps the
stored one.

- **Slack:** incoming webhook POST.
- **Email:** SMTP + STARTTLS.
- **Triggers:** `notify_on_gate` (server-side, fired when a run pauses for approval) and
  `notify_on_run_complete` (`notify_node`, with a lead summary + contact coverage counts).

`POST /settings/notifications/test` sends a test message per channel and returns the
provider error verbatim, so a bad webhook or app password is diagnosable from the UI.

## 6. Cleanup

`nodes/find.py`, `nodes/enrich.py`, `nodes/intent.py`, and `nodes/human_gate.py` were dead
copies: `graph.py` defined its own inline versions and the test suite exercised the copies,
so tests passed against code the graph never ran. `graph.py` is now wiring only, and the
`nodes/*` modules are the single implementation.
