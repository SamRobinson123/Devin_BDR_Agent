import pytest

import usage


@pytest.fixture(autouse=True)
def isolate_usage_ledger(tmp_path, monkeypatch):
    """Keep provider-call counters out of the repo's real leads.db."""
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(usage, "_ledger", None)
    yield
    usage._ledger = None
