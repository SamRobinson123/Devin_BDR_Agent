from unittest.mock import patch, MagicMock
from graph import enrich_node


def _verifier_resp(result, email):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": {"result": result, "email": email}}
    m.raise_for_status.return_value = None
    return m


@patch("graph._guess_emails")
@patch("graph.requests.get")
def test_uses_known_email_directly_without_guessing(mock_get, mock_guess):
    mock_get.return_value = _verifier_resp("deliverable", "jane@acme.com")
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe",
                         "domain": "acme.com", "email": "jane@acme.com"}]}
    result = enrich_node(state)

    mock_guess.assert_not_called()
    assert result["enriched"][0]["email"] == "jane@acme.com"
    assert result["enriched"][0]["status"] == "verified"
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["email"] == "jane@acme.com"


@patch("graph.requests.get")
def test_falls_back_to_guessing_without_known_email(mock_get):
    mock_get.return_value = _verifier_resp("deliverable", "jane.doe@acme.com")
    state = {"leads": [{"first_name": "Jane", "last_name": "Doe", "domain": "acme.com"}]}
    result = enrich_node(state)

    assert result["enriched"][0]["email"] == "jane.doe@acme.com"
    assert result["enriched"][0]["status"] == "verified"
