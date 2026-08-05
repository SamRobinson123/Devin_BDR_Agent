from unittest.mock import patch, MagicMock

import requests

from nodes.phone import phone_node


def _resp(body, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.headers = {}
    if status >= 400:
        m.raise_for_status.side_effect = requests.HTTPError(response=m)
    else:
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


@patch("nodes.phone.time.sleep", return_value=None)
@patch("nodes.phone.requests.get")
def test_retries_after_rate_limit_then_succeeds(mock_get, _sleep, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setenv("DATAGMA_API_KEY", "key123")
    mock_get.side_effect = [
        _resp({}, status=429),
        _resp({"phones": [{"number": "+1 555 0199"}]}),
    ]

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe",
                           "linkedin_url": "https://linkedin.com/in/janedoe"}]}
    result = phone_node(state)

    assert mock_get.call_count == 2
    assert result["enriched"][0]["phone"] == "+1 555 0199"
    assert result["enriched"][0]["phone_status"] == "found"


@patch("nodes.phone.time.sleep", return_value=None)
@patch("nodes.phone.requests.get")
def test_persistent_rate_limit_marks_error(mock_get, _sleep, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setenv("DATAGMA_API_KEY", "key123")
    mock_get.return_value = _resp({}, status=429)

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe",
                           "linkedin_url": "https://linkedin.com/in/janedoe"}]}
    result = phone_node(state)

    assert result["enriched"][0]["phone_status"] == "error"


@patch("nodes.phone.requests.post")
def test_prospeo_reuses_person_record_stashed_by_enrich_node(mock_post, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "prospeo")
    monkeypatch.setenv("PROSPEO_API_KEY", "key123")

    state = {"enriched": [{
        "first_name": "Dan", "last_name": "Englert", "domain": "tricentis.com",
        "_prospeo_person": {"mobile": {"revealed": True, "mobile": "+1 678-800-1234"}},
    }]}
    result = phone_node(state)

    # enrich_node already paid for this person record — phone_node must not call again.
    mock_post.assert_not_called()
    assert result["enriched"][0]["phone"] == "+1 678-800-1234"
    assert result["enriched"][0]["phone_source"] == "prospeo"


@patch("nodes.phone.requests.post")
def test_prospeo_calls_when_no_person_was_stashed(mock_post, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "prospeo")
    monkeypatch.setenv("PROSPEO_API_KEY", "key123")
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"person": {"mobile": {"revealed": True, "mobile": "+1 555 0199"}}}
    mock_post.return_value = resp

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}]}
    result = phone_node(state)

    assert mock_post.call_count == 1
    body = mock_post.call_args.kwargs["json"]
    assert body["enrich_mobile"] is True
    assert body["enrich_email"] is True
    assert result["enriched"][0]["phone"] == "+1 555 0199"


@patch("nodes.phone.requests.post")
def test_prospeo_stops_once_a_person_is_found_even_without_a_revealed_mobile(mock_post, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "prospeo")
    monkeypatch.setenv("PROSPEO_API_KEY", "key123")
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"person": {"mobile": {"revealed": False}}}
    mock_post.return_value = resp

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com",
                           "linkedin_url": "https://linkedin.com/in/janedoe"}]}
    result = phone_node(state)

    # The linkedin strategy found a real person — retrying with the name+domain
    # strategy would just re-find the same person and waste another credit.
    assert mock_post.call_count == 1
    assert result["enriched"][0]["phone_status"] == "not_found"


@patch("nodes.phone.requests.post")
def test_prospeo_tries_next_strategy_when_first_finds_no_person_at_all(mock_post, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "prospeo")
    monkeypatch.setenv("PROSPEO_API_KEY", "key123")

    def _resp(person):
        m = MagicMock()
        m.status_code = 200
        m.headers = {}
        m.raise_for_status.return_value = None
        m.json.return_value = {"person": person}
        return m

    mock_post.side_effect = [_resp(None), _resp({"mobile": {"revealed": True, "mobile": "+1 555 0199"}})]

    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com",
                           "linkedin_url": "https://linkedin.com/in/janedoe"}]}
    result = phone_node(state)

    # Strategy 1 (linkedin) found nobody, so the ladder moves on to strategy 2 (name+domain).
    assert mock_post.call_count == 2
    assert result["enriched"][0]["phone"] == "+1 555 0199"


def test_missing_api_key_degrades_to_passthrough(monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.delenv("DATAGMA_API_KEY", raising=False)
    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe", "company": "Acme"}]}
    with patch("nodes.phone.requests.get") as mock_get:
        result = phone_node(state)
    mock_get.assert_not_called()
    assert result["enriched"][0]["phone_status"] == "not_found"
