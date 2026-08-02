from unittest.mock import patch, MagicMock

import requests

from nodes.enrich import enrich_node


def _resp(result):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": {"result": result}}
    m.raise_for_status.return_value = None
    return m


@patch("nodes.enrich.requests.get")
def test_enrich_marks_verified(mock_get):
    mock_get.return_value = _resp("deliverable")
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] == "jane.doe@acme.com"
    assert result["enriched"][0]["status"] == "verified"


@patch("nodes.enrich.requests.get")
def test_enrich_accepts_risky_when_nothing_is_deliverable(mock_get):
    mock_get.return_value = _resp("risky")
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] == "jane.doe@acme.com"
    assert result["enriched"][0]["status"] == "verified"


@patch("nodes.enrich.requests.get")
def test_enrich_marks_not_found(mock_get):
    mock_get.return_value = _resp("undeliverable")
    state = {"leads": [{"first_name": "No", "last_name": "One", "domain": "x.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "not_found"


@patch("nodes.enrich.requests.get")
def test_enrich_marks_error_when_hunter_fails(mock_get):
    mock_get.side_effect = requests.RequestException("500")
    state = {"leads": [{"first_name": "A", "last_name": "B", "domain": "y.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "error"


def test_enrich_marks_error_when_lead_has_no_domain():
    state = {"leads": [{"first_name": "A", "last_name": "B"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "error"
