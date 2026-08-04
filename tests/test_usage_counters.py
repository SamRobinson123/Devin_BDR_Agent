"""Only calls a paid provider actually answered may land in the usage ledger."""

import pytest
import requests

import usage
from nodes import enrich, phone


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture
def recorded(monkeypatch):
    events = []
    monkeypatch.setattr(usage, "_record", events.append)
    return events


def test_hunter_verification_is_not_counted_when_the_call_fails(recorded, monkeypatch):
    monkeypatch.setattr(enrich.requests, "get",
                        lambda *a, **k: FakeResponse(status_code=429))
    with pytest.raises(requests.HTTPError):
        enrich._verify_email("jane@acme.com")
    assert recorded == []


def test_hunter_verification_is_counted_once_per_answered_call(recorded, monkeypatch):
    monkeypatch.setattr(enrich.requests, "get",
                        lambda *a, **k: FakeResponse({"data": {"result": "deliverable"}}))
    enrich._verify_email("jane@acme.com")
    assert [e["kind"] for e in recorded] == ["verification"]


def test_phone_lookup_is_not_counted_when_no_request_is_made(recorded, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setattr(phone.requests, "get",
                        lambda *a, **k: pytest.fail("no request expected"))

    result = phone._find_phone({"first_name": "Jane"}, phone._datagma_lookup, "key")

    assert result["phone_status"] == "not_found"
    assert recorded == []


def test_phone_lookup_is_counted_when_the_provider_answers(recorded, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setattr(phone.requests, "get",
                        lambda *a, **k: FakeResponse({"mobile": "+14155550123"}))

    result = phone._find_phone({"linkedin_url": "in/jane"}, phone._datagma_lookup, "key")

    assert result["phone"] == "+14155550123"
    assert [e["kind"] for e in recorded] == ["phone_lookup"]
    assert recorded[0]["provider"] == "datagma"


def test_phone_lookup_is_not_counted_when_the_provider_errors(recorded, monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "datagma")
    monkeypatch.setattr(phone.requests, "get",
                        lambda *a, **k: FakeResponse(status_code=500))

    result = phone._find_phone({"linkedin_url": "in/jane"}, phone._datagma_lookup, "key")

    assert result["phone_status"] == "error"
    assert recorded == []
