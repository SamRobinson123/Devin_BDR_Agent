import os
from db import init_db, get_setting
from notifications import SETTINGS_KEY, merge_defaults, notify, run_report
from state import AgentState


def notify_node(state: AgentState, conn=None) -> dict:
    """Send the finished run's lead summary to whichever channels the user connected."""
    conn = conn or init_db(os.getenv("LEADS_DB_PATH", "leads.db"))
    settings = merge_defaults(get_setting(conn, SETTINGS_KEY))
    if not settings.get("notify_on_run_complete"):
        return {}

    leads = state.get("enriched") or state.get("leads") or []
    if not leads:
        return {}

    subject, body = run_report(leads, state.get("intent"))
    notify(settings, subject, body)
    return {}
