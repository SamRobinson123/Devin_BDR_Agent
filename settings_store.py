"""Shared helpers for the settings blobs kept in the settings table.

Each feature owns a key, a defaults dict and the subset of fields that are
secrets: secrets are stored but never echoed back to the browser.
"""


def merge_defaults(defaults: dict, stored: dict | None) -> dict:
    return {**defaults, **(stored or {})}


def redact(settings: dict, secret_fields: tuple) -> dict:
    """Settings safe to return to the UI: secrets become a set/unset flag."""
    safe = {k: v for k, v in settings.items() if k not in secret_fields}
    for field in secret_fields:
        safe[f"{field}_set"] = bool(settings.get(field))
    return safe


def apply_update(defaults: dict, secret_fields: tuple, stored: dict, update: dict) -> dict:
    """Merge a UI update, keeping an existing secret when the field is left blank."""
    merged = merge_defaults(defaults, stored)
    for key, value in update.items():
        if key in secret_fields and not value:
            continue
        if key in defaults:
            merged[key] = value
    return merged
