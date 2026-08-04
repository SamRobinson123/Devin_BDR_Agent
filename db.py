import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT,
    last_name TEXT,
    company TEXT,
    domain TEXT,
    email TEXT,
    status TEXT DEFAULT 'pending',
    phone TEXT,
    phone_status TEXT DEFAULT 'pending',
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(first_name, last_name, domain)
)
"""

# Columns added after the original schema shipped; applied to existing DBs by _migrate.
EXTRA_COLUMNS = {
    "title": "TEXT",
    "linkedin_url": "TEXT",
    "seniority": "TEXT",
    "tenure": "TEXT",
    "prior_companies": "TEXT",
    "person_summary": "TEXT",
    "talking_points": "TEXT",
    "profile_sources": "TEXT",
    "phone_source": "TEXT",
    "location": "TEXT",
    "industry": "TEXT",
    "employee_count": "TEXT",
    "research_summary": "TEXT",
    "fit_score": "INTEGER",
    "fit_reason": "TEXT",
    "draft_subject": "TEXT",
    "draft_body": "TEXT",
}

PROFILE_FIELDS = ("company", "title", "linkedin_url", "location", "industry",
                  "employee_count", "research_summary", "fit_score", "fit_reason",
                  "draft_subject", "draft_body", "seniority", "tenure",
                  "prior_companies", "person_summary", "talking_points",
                  "profile_sources")

# Profile fields the model returns as lists; stored as JSON text.
JSON_FIELDS = ("prior_companies", "talking_points", "profile_sources")

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT,
    requests INTEGER NOT NULL DEFAULT 1,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
)
"""

USAGE_SUMS = ("SUM(requests) AS requests, SUM(input_tokens) AS input_tokens, "
              "SUM(output_tokens) AS output_tokens, "
              "SUM(cache_read_tokens) AS cache_read_tokens, "
              "SUM(cache_write_tokens) AS cache_write_tokens, "
              "SUM(cost_usd) AS cost_usd")


def _migrate(conn: sqlite3.Connection) -> None:
    present = {r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for name, coltype in EXTRA_COLUMNS.items():
        if name not in present:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {name} {coltype}")
    conn.commit()


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.execute(SETTINGS_SCHEMA)
    conn.execute(USAGE_SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(field: str, value):
    return json.dumps(value) if field in JSON_FIELDS and not isinstance(value, str) else value


def _decode(field: str, value):
    if field not in JSON_FIELDS or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: _decode(k, v) for k, v in dict(row).items()}


def get_setting(conn: sqlite3.Connection, key: str) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else {}


def set_setting(conn: sqlite3.Connection, key: str, value: dict) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (key, json.dumps(value), _now()),
    )
    conn.commit()


def record_usage_event(conn: sqlite3.Connection, event: dict) -> None:
    conn.execute(
        "INSERT INTO usage_events (ts, provider, kind, model, requests, input_tokens, "
        "output_tokens, cache_read_tokens, cache_write_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event.get("ts") or _now(), event["provider"], event["kind"], event.get("model"),
         int(event.get("requests", 1)), int(event.get("input_tokens", 0)),
         int(event.get("output_tokens", 0)), int(event.get("cache_read_tokens", 0)),
         int(event.get("cache_write_tokens", 0)), float(event.get("cost_usd", 0.0))),
    )
    conn.commit()


def _usage_filter(since: str, provider: str | None) -> tuple[str, list]:
    if provider:
        return "WHERE ts >= ? AND provider = ?", [since, provider]
    return "WHERE ts >= ?", [since]


def usage_grouped(conn: sqlite3.Connection, group_by: str, since: str,
                  provider: str | None = None) -> list[dict]:
    """Aggregate the usage ledger by 'day', 'provider', 'model' or 'kind'."""
    columns = {"day": "substr(ts, 1, 10)", "provider": "provider",
               "model": "model", "kind": "kind"}
    column = columns[group_by]
    where, params = _usage_filter(since, provider)
    rows = conn.execute(
        f"SELECT {column} AS {group_by}, {USAGE_SUMS} FROM usage_events "
        f"{where} GROUP BY {column} ORDER BY {group_by}",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def usage_totals(conn: sqlite3.Connection, since: str,
                 provider: str | None = None) -> dict:
    where, params = _usage_filter(since, provider)
    row = conn.execute(f"SELECT {USAGE_SUMS} FROM usage_events {where}", params).fetchone()
    return {k: v or 0 for k, v in dict(row).items()}


def upsert_lead(conn: sqlite3.Connection, lead: dict) -> int:
    now = _now()
    existing = conn.execute(
        "SELECT id FROM leads WHERE first_name = ? AND last_name = ? AND domain = ?",
        (lead.get("first_name"), lead.get("last_name"), lead.get("domain")),
    ).fetchone()
    if existing:
        _update_profile(conn, existing["id"], lead)
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO leads (first_name, last_name, company, domain, source, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (lead.get("first_name"), lead.get("last_name"), lead.get("company"),
         lead.get("domain"), lead.get("source"), now, now),
    )
    lead_id = cur.lastrowid
    conn.commit()
    _update_profile(conn, lead_id, lead)
    return lead_id


def _update_profile(conn: sqlite3.Connection, lead_id: int, lead: dict) -> None:
    """Write whichever profile/research/draft fields the lead carries; leave the rest."""
    fields = {k: _encode(k, lead[k]) for k in PROFILE_FIELDS if lead.get(k) is not None}
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE leads SET {assignments}, updated_at = ? WHERE id = ?",
        (*fields.values(), _now(), lead_id),
    )
    conn.commit()


def list_leads(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute("SELECT * FROM leads WHERE status = ?", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_leads_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM leads WHERE id IN ({placeholders})", ids).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_lead_enrichment(conn: sqlite3.Connection, lead_id: int, email, status,
                            phone, phone_status) -> None:
    conn.execute(
        "UPDATE leads SET email = ?, status = ?, phone = ?, phone_status = ?, "
        "updated_at = ? WHERE id = ?",
        (email, status, phone, phone_status, _now(), lead_id),
    )
    conn.commit()


def set_phone_source(conn: sqlite3.Connection, lead_id: int, source: str | None) -> None:
    conn.execute(
        "UPDATE leads SET phone_source = ?, updated_at = ? WHERE id = ?",
        (source, _now(), lead_id),
    )
    conn.commit()


def insert_csv_rows(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    inserted = 0
    errors = []
    for i, row in enumerate(rows):
        if not (row.get("first_name") and row.get("last_name") and row.get("domain")):
            errors.append({"row": i, "reason": "missing required field (first_name, last_name, domain)"})
            continue
        upsert_lead(conn, {**row, "source": "csv_upload"})
        inserted += 1
    return {"inserted": inserted, "errors": errors}
