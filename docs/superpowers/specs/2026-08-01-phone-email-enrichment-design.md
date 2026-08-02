# Phone + Email Enrichment Improvements — Design Spec

**Date:** 2026-08-01
**Status:** Approved design, pre-implementation
**File under construction:** `graph.py`

---

## 1. Purpose

Two improvements to the existing BDR agent graph (see
`docs/superpowers/specs/2026-07-31-bdr-agent-graph-design.md`):

1. **Stop wasting Hunter calls on guessed emails when the answer is already visible.**
   `find_node`'s web search sometimes surfaces a lead's actual email or phone number on
   the page it reads. Today that information is discarded — `find_node` only extracts
   `first_name`/`last_name`/`company`/`domain`. `find_node` will now capture `email`/
   `phone` when present, and `enrich_node` will verify a found email directly instead of
   guessing patterns.
2. **Surface phone numbers `find_node` already found, via a dedicated node.** Hunter has
   no phone data, and no evaluated third-party provider has a workable free/no-API-cost
   path to programmatic phone lookups (see "Provider evaluation" below). So phone
   enrichment is web-search-only for now: `apollo_phone_node` passes through whatever
   `phone` value `find_node` already captured; it makes no external API calls itself.

**Provider evaluation (why no paid API call):** Apollo's `people/match` (People
Enrichment) endpoint returned `403 API_INACCESSIBLE` against this project's live
account — that endpoint is paywalled off the Free plan entirely, independent of credit
balance. Apollo's `reveal_phone_number` waterfall flow (the feature that would return
real phone numbers) is also asynchronous — it requires a public `webhook_url` Apollo
calls back minutes later, which this project has no infrastructure to receive. Other
providers checked (Lusha, Cognism, ZoomInfo) have no usable free/self-serve tier for
phone data either. Conclusion: no API integration for phones right now; revisit if/when
a paid plan is in place. The node is still named `apollo_phone_node` and kept in the
graph as the designated seam for that future work.

## 2. Architecture & flow

```
                    find_node ──► human_gate ──► enrich_node ──► apollo_phone_node ──► END
intent_node ─(enrich_leads)───────────────────────► enrich_node ──► apollo_phone_node ──► END
```

`apollo_phone_node` is a new node appended unconditionally after `enrich_node` in both
places `enrich_node` is currently reached. Every enrich pass now always does email
*and* phone, back to back — one "enrich" action covers both, matching the current
human-gate prompt wording ("Reply 'enrich' to validate emails...", which will be
updated to mention phone too — see Section 6).

## 3. `find_node` changes

`FIND_SYSTEM` prompt gains new optional keys the model can populate when its search
results actually show them:

```python
FIND_SYSTEM = SystemMessage(content=(
    "You are a BDR research assistant. Use web search to find real people matching "
    "the user's criteria. Return ONLY a JSON array; each item must have keys "
    "first_name, last_name, company, domain, and — only if visible in your search "
    "results — email and phone. Omit email/phone entirely if not directly found; "
    "never guess them. No prose, no markdown fences."
))
```

`_parse_leads` is unchanged (it already accepts arbitrary JSON object shapes per lead).
No schema enforcement beyond the prompt — same "instruction does the enforcing" pattern
`find_node` already uses for `first_name`/`last_name`/etc.

## 4. `enrich_node` changes (email)

```
if lead.get("email"):
    verify that exact email via Hunter's /v2/email-verifier
    status = "verified" if result == "deliverable"/"risky", else "not_found"
else:
    (existing behavior) _guess_emails + verify each candidate
```

This reuses the existing `_verify_email` helper — only the branch that decides *which*
email(s) to try changes. No new Hunter endpoint.

## 5. `apollo_phone_node` (new node, no external API call)

**Per-lead logic:**
```
if lead.get("phone"):
    phone = lead["phone"]; phone_status = "found"   # from find_node's web search
else:
    phone = None; phone_status = "not_found"
```

**Output:** `apollo_phone_node` reads `state["enriched"]` (already populated by
`enrich_node`) and returns an updated `state["enriched"]` with `phone`/`phone_status`
merged onto each existing lead dict — not a separate state key. This mirrors how
`enrich_node` merges onto `state["leads"]`.

## 6. Human gate prompt update

`human_gate`'s message changes from:
> "Found {N} leads. Reply 'enrich' to validate emails via Hunter, or 'done' to stop."

to:
> "Found {N} leads. Reply 'enrich' to validate emails and look up phone numbers, or
> 'done' to stop."

No change to `route_after_gate` or the `gate_decision` values (`"enrich"`/`"done"`) —
wording only.

## 7. Error handling

- `apollo_phone_node` makes no external calls, so it has no error/network-exception
  path of its own — a lead simply gets `phone_status: "not_found"` when `find_node`
  didn't surface one.
- Existing Hunter guess-and-verify path for emails is unchanged when `find_node` didn't
  surface one directly.

## 8. Testing

- Unit — `apollo_phone_node`: (a) lead already has `phone` → `phone_status: "found"`;
  (b) lead has no `phone` → `phone_status: "not_found"`.
- Unit — `enrich_node`: new case where `lead["email"]` is already set → asserts the
  guess helper is never called, verifier is called with that exact email.
- Integration: extend the graph test to assert a lead (seeded with a `phone` as if
  `find_node` had found one) ends up with both `email`/`status` (from `enrich_node`)
  and `phone`/`phone_status` (from `apollo_phone_node`) after one `app.invoke`.

## 9. Success criteria

1. A lead whose email was already visible in search results is verified directly, no
   guessed candidates attempted.
2. A lead with no visible email still gets the existing guess-and-verify treatment.
3. Every enrich pass (either graph path) also runs `apollo_phone_node`, which surfaces
   any phone `find_node` already captured.
4. No live Apollo (or other paid provider) API calls happen anywhere in this flow.
5. Hunter failures on one lead never break enrichment of the rest of the batch.
