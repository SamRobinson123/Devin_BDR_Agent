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
                  "draft_subject", "draft_body")


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
    conn.commit()
    _migrate(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


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
    fields = {k: lead[k] for k in PROFILE_FIELDS if lead.get(k) is not None}
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
