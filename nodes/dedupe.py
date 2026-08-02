import os
from db import init_db, list_leads
from state import AgentState


def _key(lead: dict) -> tuple:
    return (
        (lead.get("first_name") or "").strip().lower(),
        (lead.get("last_name") or "").strip().lower(),
        (lead.get("domain") or "").strip().lower(),
    )


def dedupe_node(state: AgentState, conn=None) -> dict:
    """Drop prospects already in the leads DB, plus duplicates inside the batch."""
    conn = conn or init_db(os.getenv("LEADS_DB_PATH", "leads.db"))
    known = {_key(row) for row in list_leads(conn)}

    fresh, skipped, seen = [], [], set()
    for lead in state.get("leads", []):
        key = _key(lead)
        if key in known or key in seen:
            skipped.append(lead)
            continue
        seen.add(key)
        fresh.append(lead)

    return {"leads": fresh, "skipped": skipped}
