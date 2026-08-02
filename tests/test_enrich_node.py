from unittest.mock import patch, MagicMock
from nodes.enrich import enrich_node


def _resp(json_body, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_body
    return m


@patch("nodes.enrich.requests.get")
def test_enrich_marks_verified(mock_get):
    mock_get.return_value = _resp(
        {"data": {"email": "jane@acme.com", "score": 96}}
    )
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] == "jane@acme.com"
    assert result["enriched"][0]["status"] == "verified"


@patch("nodes.enrich.requests.get")
def test_enrich_marks_not_found(mock_get):
    mock_get.return_value = _resp({"data": {"email": None}})
    state = {"leads": [{"first_name": "No", "last_name": "One", "domain": "x.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "not_found"


@patch("nodes.enrich.requests.get")
def test_enrich_marks_error_on_bad_status(mock_get):
    mock_get.return_value = _resp({}, status_code=500)
    state = {"leads": [{"first_name": "A", "last_name": "B", "domain": "y.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "error"
