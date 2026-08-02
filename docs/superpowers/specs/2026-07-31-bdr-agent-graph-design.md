# BDR Agent Graph — Design Spec

**Date:** 2026-07-31
**Status:** Approved design, pre-implementation
**File under construction:** `graph.py`

---

## 1. Purpose

A LangGraph agent for business-development (BDR) work. In this first version it does
exactly two things:

- **Find leads** — Claude uses Anthropic web search to find people/companies matching
  the user's criteria.
- **Enrich leads** — Hunter finds and validates email addresses for known leads.

An **intent node** deciphers which of these the user wants and routes accordingly.
After the find branch, the graph pauses (**human-in-the-loop**) and asks the user what
to do next before optionally enriching.

Out of scope for now (YAGNI): Apollo, outreach sequences, account-research briefs,
writing results back to the Synapse warehouse.

## 2. Available resources (from `.env` / `constants.py`)

| Resource | Used for | In this version? |
|---|---|---|
| Anthropic (Claude) | intent classification + web search | Yes |
| Hunter (`HUNTER_API_KEY`) | email find + validation | Yes |
| LangSmith | tracing/observability | Optional, passive |
| Synapse (`SYNAPSE_CONN_STR`) | internal warehouse | Not yet |
| Apollo (`APOLLO_API_KEY`) | prospecting/enrichment | Not used |
| OpenAI | alt model provider | Not used |

**Known fix:** `constants.py` sets `model="claude-sonnet-4-6"`, which is not a valid
model ID. Use `claude-sonnet-4-5` (or `claude-sonnet-5`) before running.

## 3. Architecture & flow

```
                                          ┌─ "find_leads" ──► find_node (web search)
START ─► intent_node ─(route by intent)─┤                        │
                                          │                   human_gate: interrupt()
                                          │                   asks user: enrich? refine? done?
                                          │                        │
                                          │              ┌─(route by user answer)─┐
                                          │              │                        │
                                          └─ "enrich_leads" ─────► enrich_node ───┴──► END
                                                                   (Hunter)
```

- `intent_node` classifies the request into `find_leads`, `enrich_leads`, or `clarify`.
- **Find path:** `find_node` web-searches → `human_gate` pauses and asks the user what
  to do → the answer routes either into the shared `enrich_node` or to `END`.
- **Enrich path:** routes straight to the shared `enrich_node`.
- `enrich_node` (Hunter) is reached by **both** paths — this is the shared-node design
  (Approach A): Hunter logic lives in exactly one place.

## 4. State

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: str          # "find_leads" | "enrich_leads" | "clarify"
    leads: list          # candidate leads produced by find_node
    enriched: list       # leads + validated emails produced by enrich_node
```

`add_messages` is a reducer: message updates append rather than overwrite.
`find_node` writes `leads`; `enrich_node` reads `leads`, calls Hunter, writes `enriched`.

## 5. Components (one job each)

| Component | Type | Job | Depends on |
|---|---|---|---|
| `Intent` | pydantic `BaseModel` | validated `{category, query}` | — |
| `intent_node` | LLM structured output | classify request → `state["intent"]` | Claude |
| `find_node` | LLM + web search tool | web search → `state["leads"]` | Claude web search |
| `human_gate` | `interrupt()` + router | pause, ask user, route on answer | checkpointer |
| `enrich_node` | plain API call | Hunter find/verify emails → `state["enriched"]` | Hunter API |
| `route_by_intent` | router fn | read `state["intent"]` → branch name | — |
| build/compile | graph wiring | register nodes + edges, `compile(checkpointer=MemorySaver())` | LangGraph |

### Intent taxonomy
```python
class Intent(BaseModel):
    category: Literal["find_leads", "enrich_leads", "clarify"]
    query: str   # cleaned-up criteria or target
```
`clarify` is the "ask first" escape hatch: when the request is ambiguous, the agent
asks a question instead of guessing.

## 6. Human-in-the-loop gate

After `find_node`, `human_gate` calls `interrupt()` with the found leads and a prompt
like: *"Found N leads. Enrich emails via Hunter, refine the search, or stop?"*
The checkpointer (`MemorySaver`) persists state so the run resumes on the user's reply.
The reply routes to:
- **enrich** → shared `enrich_node`
- **refine** → back to `find_node` (future; can start as "stop" + user re-asks)
- **done** → `END`

## 7. Error handling

- **Ambiguous request:** `intent_node` returns `clarify` → agent asks a question, no
  tool runs.
- **Web search returns nothing:** `find_node` writes empty `leads`; `human_gate`
  reports "no leads found" and does not proceed to Hunter.
- **Hunter failure / email not found:** each lead carries a `status` field
  (`verified` / `not_found` / `error`); a single failed lookup never breaks the batch.

## 8. Testing

- Unit: `intent_node` maps sample phrasings to the right category (LLM mocked).
- Unit: `enrich_node` maps a fake Hunter response to correct `status` values.
- Integration: run the compiled graph on a canned request with web search + Hunter
  mocked; assert the final state's `leads` / `enriched`.

## 9. Success criteria

1. A "find" request returns web-sourced leads in `state["leads"]`.
2. After find, the graph pauses and waits for a human decision.
3. Choosing "enrich" (or an "enrich" intent directly) returns leads with Hunter-
   validated email `status` in `state["enriched"]`.
4. Ambiguous requests produce a clarifying question, not a guess.
5. Adding a future capability touches three spots only: the `Intent` taxonomy, one new
   node, and one route entry.
```
