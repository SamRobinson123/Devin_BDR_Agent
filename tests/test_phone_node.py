from unittest.mock import patch, MagicMock

import requests

from nodes.phone import phone_node


def _resp(body):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = body
    m.raise_for_status.return_value = None
    return m


def test_uses_phone_already_found_by_web_search(monkeypatch):
    monkeypatch.delenv("PHONE_PROVIDER", raising=False)
    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe",
                           "domain": "acme.com", "phone": "+1-555-0100"}]}
    result = phone_node(state)
    assert result["enriched"][0]["phone"] == "+1-555-0100"
    assert result["enriched"][0]["phone_status"] == "found"
    assert result["enriched"][0]["phone_source"] == "web_search"


def test_no_provider_configured_makes_no_calls(monkeypatch):
    monkeypatch.delenv("PHONE_PROVIDER", raising=False)
    state = {"enriched": [{"first_name": "No", "last_name": "One", "domain": "x.com"}]}
    with patch("nodes.phone.requests.get") as mock_get:
        result = phone_node(state)
    mock_get.assert_not_called()
    assert result["enriched"][0]["phone"] is None
    assert result["enriched"][0]["phone_status"] == "not_found"


@patch("nodes.phone.requests.get")
def test_datagma_lookup_by_linkedin_url(mock_get, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setenv("DATAGMA_API_KEY", "key123")
    mock_get.return_value = _resp({"phones": [{"number": "+1 555 0199"}]})

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe",
                           "linkedin_url": "https://linkedin.com/in/janedoe"}]}
    result = phone_node(state)

    assert result["enriched"][0]["phone"] == "+1 555 0199"
    assert result["enriched"][0]["phone_source"] == "datagma"
    assert mock_get.call_args.kwargs["params"]["username"] == "https://linkedin.com/in/janedoe"


@patch("nodes.phone.requests.get")
def test_datagma_falls_back_to_name_and_company(mock_get, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setenv("DATAGMA_API_KEY", "key123")
    mock_get.return_value = _resp({})

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme"}]}
    result = phone_node(state)

    assert mock_get.call_args.kwargs["params"]["fullName"] == "Jane Doe"
    assert result["enriched"][0]["phone_status"] == "not_found"


@patch("nodes.phone.requests.get")
def test_provider_error_marks_error(mock_get, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setenv("DATAGMA_API_KEY", "key123")
    mock_get.side_effect = requests.RequestException("boom")

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme"}]}
    result = phone_node(state)
    assert result["enriched"][0]["phone_status"] == "error"


def test_missing_api_key_degrades_to_passthrough(monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.delenv("DATAGMA_API_KEY", raising=False)
    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme"}]}
    with patch("nodes.phone.requests.get") as mock_get:
        result = phone_node(state)
    mock_get.assert_not_called()
    assert result["enriched"][0]["phone_status"] == "not_found"
