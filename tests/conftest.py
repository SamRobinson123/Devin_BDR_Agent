import pytest

import usage


_PROVIDER_ENV_VARS = ("ANTHROPIC_API_KEY",)


@pytest.fixture(autouse=True)
def isolate_usage_ledger(tmp_path, monkeypatch):
    """Keep provider-call counters out of the repo's real leads.db, and keep the
    suite hermetic: a local .env must never make tests hit real provider APIs."""
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(usage, "_ledger", None)
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    usage._ledger = None
