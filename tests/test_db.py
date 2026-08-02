import sqlite3
import pytest
from db import init_db, upsert_lead, list_leads, get_leads_by_ids, update_lead_enrichment, insert_csv_rows


@pytest.fixture
def conn():
    return init_db(":memory:")


def test_init_db_creates_leads_table(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
    assert cur.fetchone() is not None


def test_upsert_lead_inserts_new_row(conn):
    lead_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                  "domain": "acme.com", "company": "Acme",
                                  "source": "chat"})
    rows = list_leads(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == lead_id
    assert rows[0]["status"] == "pending"


def test_upsert_lead_updates_existing_row_not_duplicate(conn):
    first_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                   "domain": "acme.com", "company": "Acme",
                                   "source": "chat"})
    second_id = upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                                    "domain": "acme.com", "company": "Acme Corp",
                                    "source": "chat"})
    rows = list_leads(conn)
    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme Corp"


def test_get_leads_by_ids_returns_matching_rows(conn):
    id1 = upsert_lead(conn, {"first_name": "A", "last_name": "B", "domain": "a.com", "source": "chat"})
    id2 = upsert_lead(conn, {"first_name": "C", "last_name": "D", "domain": "c.com", "source": "chat"})
    rows = get_leads_by_ids(conn, [id1, id2])
    assert {r["id"] for r in rows} == {id1, id2}


def test_update_lead_enrichment_writes_email_and_phone(conn):
    lead_id = upsert_lead(conn, {"first_name": "A", "last_name": "B", "domain": "a.com", "source": "chat"})
    update_lead_enrichment(conn, lead_id, email="a.b@a.com", status="verified",
                            phone="+1-555-0100", phone_status="found")
    row = get_leads_by_ids(conn, [lead_id])[0]
    assert row["email"] == "a.b@a.com"
    assert row["status"] == "verified"
    assert row["phone"] == "+1-555-0100"
    assert row["phone_status"] == "found"


def test_insert_csv_rows_inserts_valid_rows(conn):
    rows = [
        {"first_name": "Jane", "last_name": "Doe", "domain": "acme.com", "company": "Acme"},
        {"first_name": "No", "last_name": "Domain", "domain": ""},
    ]
    result = insert_csv_rows(conn, rows)
    assert result["inserted"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row"] == 1
    all_leads = list_leads(conn)
    assert len(all_leads) == 1
    assert all_leads[0]["source"] == "csv_upload"
