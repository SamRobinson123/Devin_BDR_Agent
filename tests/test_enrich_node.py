from unittest.mock import patch, MagicMock

import requests

from nodes.enrich import enrich_node


def _resp(status, score=None, accept_all=False):
    """Hunter's verifier response shape. `result` is deprecated in favor of
    `status`; `accept_all` marks a catch-all domain where the verifier can't
    tell a real address from a made-up one."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": {"status": status, "score": score, "accept_all": accept_all}}
    m.raise_for_status.return_value = None
    return m


@patch("nodes.enrich.requests.get")
def test_enrich_marks_verified(mock_get):
    mock_get.return_value = _resp("valid", score=95)
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] == "jane.doe@acme.com"
    assert result["enriched"][0]["status"] == "verified"
    assert result["enriched"][0]["email_confidence"] == 95


@patch("nodes.enrich.requests.get")
def test_enrich_marks_unverifiable_on_catchall_domain(mock_get):
    # Every candidate comes back accept_all — the verifier can't distinguish
    # a real address from a made-up one here, so nothing should be guessed at.
    mock_get.return_value = _resp("accept_all", score=74, accept_all=True)
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["email"] is None
    assert result["enriched"][0]["status"] == "unverifiable"
    assert result["enriched"][0]["email_confidence"] is None
    # Stops at the first accept_all response instead of burning the whole candidate list.
    assert mock_get.call_count == 1


@patch("nodes.enrich.requests.get")
def test_enrich_marks_not_found(mock_get):
    mock_get.return_value = _resp("invalid")
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


@patch("nodes.enrich.requests.get")
def test_enrich_keeps_trying_other_patterns_after_one_request_fails(mock_get):
    mock_get.side_effect = [
        requests.RequestException("rate limited"),
        _resp("valid", score=90),
    ]
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "verified"
    assert mock_get.call_count == 2


def test_enrich_marks_error_when_lead_has_no_domain():
    state = {"leads": [{"first_name": "A", "last_name": "B"}],
             "intent": "enrich_leads", "messages": [], "enriched": []}
    result = enrich_node(state)
    assert result["enriched"][0]["status"] == "error"


@patch("nodes.enrich.prospeo_enrich_person")
def test_prospeo_revealed_email_is_authoritative_and_skips_hunter(mock_prospeo, monkeypatch):
    monkeypatch.setenv("PROSPEO_API_KEY", "test-key")
    mock_prospeo.return_value = {
        "email": {"revealed": True, "email": "d.englert@tricentis.com"},
        "mobile": {"revealed": False},
    }
    with patch("nodes.enrich.requests.get") as mock_get:
        state = {"leads": [{"first_name": "Dan", "last_name": "Englert", "domain": "tricentis.com"}],
                 "intent": "enrich_leads", "messages": [], "enriched": []}
        result = enrich_node(state)
        # Prospeo's answer is authoritative — Hunter's guess+verify ladder never runs.
        mock_get.assert_not_called()

    lead = result["enriched"][0]
    assert lead["email"] == "d.englert@tricentis.com"
    assert lead["status"] == "verified"
    assert lead["email_confidence"] == 100
    assert lead["_prospeo_person"] == mock_prospeo.return_value


@patch("nodes.enrich.prospeo_enrich_person")
def test_falls_back_to_hunter_when_prospeo_has_no_email(mock_prospeo, monkeypatch):
    monkeypatch.setenv("PROSPEO_API_KEY", "test-key")
    mock_prospeo.return_value = {"email": {"revealed": False}, "mobile": {"revealed": False}}
    with patch("nodes.enrich.requests.get") as mock_get:
        mock_get.return_value = _resp("valid", score=88)
        state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
                 "intent": "enrich_leads", "messages": [], "enriched": []}
        result = enrich_node(state)

    lead = result["enriched"][0]
    assert lead["email"] == "jane.doe@acme.com"
    assert lead["status"] == "verified"
    # Prospeo's (email-less) person record is still stashed for phone_node to reuse.
    assert lead["_prospeo_person"] == mock_prospeo.return_value


@patch("nodes.enrich.prospeo_enrich_person")
def test_prospeo_error_falls_back_to_hunter_without_crashing(mock_prospeo, monkeypatch):
    monkeypatch.setenv("PROSPEO_API_KEY", "test-key")
    mock_prospeo.side_effect = requests.RequestException("insufficient credits")
    with patch("nodes.enrich.requests.get") as mock_get:
        mock_get.return_value = _resp("valid", score=80)
        state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
                 "intent": "enrich_leads", "messages": [], "enriched": []}
        result = enrich_node(state)

    assert result["enriched"][0]["status"] == "verified"
    assert "_prospeo_person" not in result["enriched"][0]


def test_hunter_finder_disabled_by_default(monkeypatch):
    # HUNTER_FINDER_ENABLED isn't set, so the Finder's dead 0-quota endpoint
    # should never be called at all — only the verifier runs, once.
    with patch("nodes.enrich.requests.get") as mock_get:
        mock_get.return_value = _resp("valid", score=90)
        state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}],
                 "intent": "enrich_leads", "messages": [], "enriched": []}
        enrich_node(state)
        assert mock_get.call_count == 1
