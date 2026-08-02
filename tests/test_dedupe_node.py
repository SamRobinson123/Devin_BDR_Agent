import pytest
from db import init_db, upsert_lead
from nodes.dedupe import dedupe_node


@pytest.fixture
def conn():
    return init_db(":memory:")


def test_skips_leads_already_in_db(conn):
    upsert_lead(conn, {"first_name": "Jane", "last_name": "Doe",
                       "domain": "acme.com", "source": "csv_upload"})
    state = {"leads": [
        {"first_name": "jane", "last_name": "DOE", "domain": "Acme.com"},
        {"first_name": "New", "last_name": "Person", "domain": "beta.com"},
    ]}

    result = dedupe_node(state, conn=conn)

    assert [lead["first_name"] for lead in result["leads"]] == ["New"]
    assert [lead["first_name"] for lead in result["skipped"]] == ["jane"]


def test_drops_duplicates_within_the_batch(conn):
    state = {"leads": [
        {"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"},
        {"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"},
    ]}

    result = dedupe_node(state, conn=conn)

    assert len(result["leads"]) == 1
    assert len(result["skipped"]) == 1
