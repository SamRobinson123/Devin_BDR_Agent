from unittest.mock import patch, MagicMock

import requests

import notifications


def test_redact_hides_secrets_but_reports_whether_they_are_set():
    settings = notifications.merge_defaults({
        "slack_webhook_url": "https://hooks.slack.com/x", "smtp_password": "",
    })
    safe = notifications.redact(settings)
    assert "slack_webhook_url" not in safe
    assert safe["slack_webhook_url_set"] is True
    assert safe["smtp_password_set"] is False


def test_apply_update_keeps_existing_secret_when_field_left_blank():
    stored = {"slack_webhook_url": "https://hooks.slack.com/old", "slack_enabled": False}
    merged = notifications.apply_update(stored, {"slack_enabled": True, "slack_webhook_url": ""})
    assert merged["slack_webhook_url"] == "https://hooks.slack.com/old"
    assert merged["slack_enabled"] is True


def test_apply_update_ignores_unknown_keys():
    merged = notifications.apply_update({}, {"is_admin": True})
    assert "is_admin" not in merged


def test_send_slack_reports_transport_failure():
    settings = notifications.merge_defaults({"slack_webhook_url": "https://hooks.slack.com/x"})
    with patch("notifications.requests.post", side_effect=requests.RequestException("nope")):
        result = notifications.send_slack(settings, "hi")
    assert result == {"channel": "slack", "ok": False, "error": "nope"}


def test_send_email_refuses_incomplete_smtp_settings():
    result = notifications.send_email(notifications.merge_defaults({}), "s", "b")
    assert result["ok"] is False


def test_notify_only_uses_enabled_channels():
    settings = notifications.merge_defaults({
        "slack_enabled": True, "slack_webhook_url": "https://hooks.slack.com/x",
        "email_enabled": False,
    })
    with patch("notifications.requests.post", return_value=MagicMock(raise_for_status=lambda: None)):
        results = notifications.notify(settings, "subject", "body")
    assert [r["channel"] for r in results] == ["slack"]


def test_run_report_counts_contact_coverage():
    leads = [
        {"first_name": "Jane", "last_name": "Doe", "company": "Acme",
         "email": "jane@acme.com", "phone": "+15550100", "fit_score": 91},
        {"first_name": "John", "last_name": "Roe", "company": "Beta"},
    ]
    subject, body = notifications.run_report(leads, intent="find_leads")
    assert subject == "BDR agent: 2 leads ready"
    assert "2 leads · 1 with email · 1 with phone" in body
    assert "[91] Jane Doe" in body
    assert "no contact info" in body
