import json
from unittest.mock import MagicMock

from nodes.enrich import enrich_node


def _fake_llm(payload):
    """LLM whose search+fetch call returns `payload` as its JSON answer."""
    llm = MagicMock()
    response = MagicMock()
    response.content = json.dumps(payload) if isinstance(payload, dict) else payload
    llm.bind_tools.return_value.invoke.return_value = response
    return llm


FOUND = {
    "email": "jane@acmepm.com",
    "email_confidence": 95,
    "email_source": "https://acmepm.com/team",
    "phone": "+1 415 555 0123",
    "phone_confidence": "high",
    "phone_source": "https://acmepm.com/team",
}

LEAD = {"first_name": "Jane", "last_name": "Doe", "company": "Acme PM", "domain": "acmepm.com"}


def test_enrich_marks_verified_with_sources():
    result = enrich_node({"leads": [LEAD]}, llm=_fake_llm(FOUND))
    lead = result["enriched"][0]
    assert lead["email"] == "jane@acmepm.com"
    assert lead["status"] == "verified"
    assert lead["email_confidence"] == 95
    assert lead["email_source"] == "https://acmepm.com/team"
    assert lead["phone"] == "+1 415 555 0123"
    assert lead["phone_status"] == "found"
    assert lead["phone_confidence"] == "high"
    assert lead["phone_source"] == "https://acmepm.com/team"


def test_enrich_marks_not_found_when_nothing_on_the_web():
    empty = {"email": None, "email_confidence": None, "email_source": None,
             "phone": None, "phone_confidence": None, "phone_source": None}
    lead = enrich_node({"leads": [LEAD]}, llm=_fake_llm(empty))["enriched"][0]
    assert lead["email"] is None
    assert lead["status"] == "not_found"
    assert lead["phone"] is None
    assert lead["phone_status"] == "not_found"
    assert lead["phone_source"] is None


def test_enrich_marks_error_when_the_llm_call_fails():
    llm = MagicMock()
    llm.bind_tools.return_value.invoke.side_effect = RuntimeError("api down")
    lead = enrich_node({"leads": [LEAD]}, llm=llm)["enriched"][0]
    assert lead["status"] == "error"
    assert lead["phone_status"] == "error"


def test_enrich_passes_known_contact_details_for_reverification():
    llm = _fake_llm(FOUND)
    enrich_node({"leads": [{**LEAD, "email": "old@acmepm.com", "phone": "+1 415 555 0000"}]},
                llm=llm)
    prompt = llm.bind_tools.return_value.invoke.call_args.args[0][1].content
    assert "old@acmepm.com" in prompt
    assert "+1 415 555 0000" in prompt


def test_enrich_normalises_email_and_ignores_source_without_value():
    payload = {**FOUND, "email": " Jane@AcmePM.com ", "phone": None}
    lead = enrich_node({"leads": [LEAD]}, llm=_fake_llm(payload))["enriched"][0]
    assert lead["email"] == "jane@acmepm.com"
    assert lead["phone_status"] == "not_found"
    assert lead["phone_source"] is None
