import smtplib
import ssl
from email.message import EmailMessage

import requests

import settings_store

SETTINGS_KEY = "notifications"

DEFAULT_SETTINGS = {
    "slack_enabled": False,
    "slack_webhook_url": "",
    "email_enabled": False,
    "email_to": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "notify_on_run_complete": True,
    "notify_on_gate": True,
}

# Never echoed back to the browser once stored.
SECRET_FIELDS = ("slack_webhook_url", "smtp_password")


def merge_defaults(stored: dict) -> dict:
    return settings_store.merge_defaults(DEFAULT_SETTINGS, stored)


def redact(settings: dict) -> dict:
    return settings_store.redact(settings, SECRET_FIELDS)


def apply_update(stored: dict, update: dict) -> dict:
    return settings_store.apply_update(DEFAULT_SETTINGS, SECRET_FIELDS, stored, update)


def _scrub(message: str, secret: str) -> str:
    """requests embeds the request URL in its errors, which for Slack is the webhook secret."""
    return message.replace(secret, "<webhook url>") if secret else message


def send_slack(settings: dict, text: str) -> dict:
    url = settings.get("slack_webhook_url")
    if not url:
        return {"channel": "slack", "ok": False, "error": "no webhook url configured"}
    try:
        resp = requests.post(url, json={"text": text}, timeout=15)
        resp.raise_for_status()
        return {"channel": "slack", "ok": True}
    except requests.RequestException as exc:
        return {"channel": "slack", "ok": False, "error": _scrub(str(exc), url)}


def send_email(settings: dict, subject: str, body: str) -> dict:
    required = ("email_to", "smtp_host", "smtp_username", "smtp_password")
    if not all(settings.get(f) for f in required):
        return {"channel": "email", "ok": False, "error": "smtp settings incomplete"}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["smtp_username"]
    message["To"] = settings["email_to"]
    message.set_content(body)

    try:
        with smtplib.SMTP(settings["smtp_host"], int(settings.get("smtp_port") or 587),
                          timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings["smtp_username"], settings["smtp_password"])
            smtp.send_message(message)
        return {"channel": "email", "ok": True}
    except (smtplib.SMTPException, OSError) as exc:
        return {"channel": "email", "ok": False, "error": str(exc)}


def notify(settings: dict, subject: str, body: str) -> list[dict]:
    """Fan a message out to every enabled channel; never raises."""
    results = []
    if settings.get("slack_enabled"):
        results.append(send_slack(settings, f"*{subject}*\n{body}"))
    if settings.get("email_enabled"):
        results.append(send_email(settings, subject, body))
    return results


def lead_line(lead: dict) -> str:
    name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
    bits = [b for b in (lead.get("title"), lead.get("company")) if b]
    contact = [b for b in (lead.get("email"), lead.get("phone")) if b]
    score = f"[{lead['fit_score']}] " if lead.get("fit_score") is not None else ""
    tail = f" — {', '.join(contact)}" if contact else " — no contact info"
    return f"{score}{name or 'Unknown'} ({', '.join(bits) or 'unknown role'}){tail}"


def run_report(leads: list, intent: str | None = None) -> tuple[str, str]:
    """Build the (subject, body) summary sent after a completed agent run."""
    with_email = sum(1 for lead in leads if lead.get("email"))
    with_phone = sum(1 for lead in leads if lead.get("phone"))
    subject = f"BDR agent: {len(leads)} leads ready"
    header = (f"Intent: {intent or 'unknown'}\n"
              f"{len(leads)} leads · {with_email} with email · {with_phone} with phone\n")
    return subject, header + "\n".join(lead_line(lead) for lead in leads)
