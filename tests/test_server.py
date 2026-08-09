import io
from fastapi.testclient import TestClient


def test_get_leads_returns_empty_list_initially(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    resp = client.get("/leads")
    assert resp.status_code == 200
    assert resp.json() == []


def test_upload_csv_inserts_valid_rows_and_reports_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads2.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    csv_content = (
        "first_name,last_name,domain,company\n"
        "Jane,Doe,acme.com,Acme\n"
        "No,Domain,,Missing Domain Co\n"
    )
    files = {"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    resp = client.post("/leads/upload", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 1
    assert len(body["errors"]) == 1

    leads = client.get("/leads").json()
    assert len(leads) == 1
    assert leads[0]["source"] == "csv_upload"


from unittest.mock import patch, MagicMock


def _contact_llm(email="jane.doe@acme.com", phone=None):
    import json as _json
    llm = MagicMock()
    response = MagicMock()
    response.content = _json.dumps({
        "email": email, "email_confidence": 92, "email_source": "https://acme.com/team",
        "phone": phone, "phone_confidence": "high" if phone else None,
        "phone_source": "https://acme.com/team" if phone else None,
    })
    llm.bind_tools.return_value.invoke.return_value = response
    return llm


def test_enrich_endpoint_updates_db_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads3.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    csv_content = "first_name,last_name,domain,company\nJane,Doe,acme.com,Acme\n"
    files = {"file": ("leads.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    client.post("/leads/upload", files=files)
    lead_id = client.get("/leads").json()[0]["id"]

    with patch("nodes.enrich.default_search_llm", _contact_llm()):
        resp = client.post("/leads/enrich", json={"lead_ids": [lead_id]})

    assert resp.status_code == 200
    updated = client.get("/leads").json()[0]
    assert updated["email"] == "jane.doe@acme.com"
    assert updated["status"] == "verified"
    assert updated["phone_status"] == "not_found"


from langchain_core.messages import AIMessage


def _parse_sse(text: str) -> list[dict]:
    """Test helper: parse raw SSE text into a list of {"event": ..., "data": ...}."""
    import json as _json
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = _json.loads(line[len("data:"):].strip())
        events.append({"event": event_type, "data": data})
    return events


def test_chat_find_intent_streams_node_events_and_pauses(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads4.db"))
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test_agent4.db"))
    import importlib
    import graph
    importlib.reload(graph)
    from graph import Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=(
        '[{"first_name": "Jane", "last_name": "Doe", "company": "Acme", "domain": "acme.com"}]'
    ))

    with patch("graph.llm", fake_llm), patch("graph.search_llm", fake_llm):
        import server
        importlib.reload(server)

        client = TestClient(server.app)
        with client.stream(
            "POST", "/chat", json={"message": "find fintech VPs", "thread_id": "t1"}
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    node_events = [e for e in events if e["event"] == "node"]
    result_events = [e for e in events if e["event"] == "result"]

    assert [e["data"]["node"] for e in node_events] == [
        "intent_node", "find_node", "dedupe_node", "research_node", "profile_node",
        "score_node",
    ]
    assert node_events[0]["data"]["data"]["intent"] == "find_leads"

    assert len(result_events) == 1
    result = result_events[0]["data"]
    assert result["paused"] is True
    assert result["leads"][0]["first_name"] == "Jane"

    saved = client.get("/leads").json()
    assert len(saved) == 1
    assert saved[0]["first_name"] == "Jane"


def test_chat_enrich_after_gate_streams_and_updates_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads5.db"))
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test_agent5.db"))
    import importlib
    import graph
    importlib.reload(graph)
    from graph import Intent

    fake_llm = MagicMock()
    structured = MagicMock()
    fake_llm.with_structured_output.return_value = structured
    structured.invoke.return_value = Intent(category="find_leads", query="fintech VPs")

    bound = MagicMock()
    fake_llm.bind_tools.return_value = bound
    bound.invoke.return_value = AIMessage(content=(
        '[{"first_name": "Jane", "last_name": "Doe", "company": "Acme", "domain": "acme.com"}]'
    ))

    def fake_enrich(state, llm=None):
        return {"enriched": [{**lead, "email": "jane.doe@acme.com", "status": "verified",
                              "email_confidence": 92, "phone": None,
                              "phone_status": "not_found", "phone_source": None,
                              "phone_confidence": None}
                             for lead in state.get("leads", [])]}

    with patch("graph.llm", fake_llm), patch("graph.search_llm", fake_llm), \
            patch("graph.enrich_node", fake_enrich):
        import server
        importlib.reload(server)

        client = TestClient(server.app)
        with client.stream(
            "POST", "/chat", json={"message": "find fintech VPs", "thread_id": "t2"}
        ) as resp:
            "".join(resp.iter_text())

        with client.stream(
            "POST", "/chat", json={"message": "enrich", "thread_id": "t2"}
        ) as resp:
            body = "".join(resp.iter_text())

    events = _parse_sse(body)
    node_events = [e["data"]["node"] for e in events if e["event"] == "node"]
    assert node_events == ["human_gate", "enrich_node", "notify_node"]

    result = next(e["data"] for e in events if e["event"] == "result")
    assert result["paused"] is False

    saved = client.get("/leads").json()
    assert saved[0]["email"] == "jane.doe@acme.com"
    assert saved[0]["status"] == "verified"


def test_notification_settings_roundtrip_never_echoes_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads6.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    assert client.get("/settings/notifications").json()["slack_webhook_url_set"] is False

    saved = client.put("/settings/notifications", json={
        "slack_enabled": True, "slack_webhook_url": "https://hooks.slack.com/services/x",
    }).json()
    assert saved["slack_enabled"] is True
    assert "slack_webhook_url" not in saved
    assert saved["slack_webhook_url_set"] is True

    client.put("/settings/notifications", json={"slack_webhook_url": ""})
    assert client.get("/settings/notifications").json()["slack_webhook_url_set"] is True


def test_test_notification_reports_channel_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads7.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    resp = client.post("/settings/notifications/test", json={"channel": "slack"})
    assert resp.json()["ok"] is False


def test_usage_settings_roundtrip_never_echoes_the_admin_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads8.db"))
    import importlib
    import server
    importlib.reload(server)

    client = TestClient(server.app)
    assert client.get("/settings/usage").json()["anthropic_admin_key_set"] is False

    saved = client.put("/settings/usage", json={
        "anthropic_admin_key": "sk-ant-admin-x", "monthly_budget_usd": 50,
    }).json()
    assert "anthropic_admin_key" not in saved
    assert saved["anthropic_admin_key_set"] is True
    assert saved["monthly_budget_usd"] == 50

    client.put("/settings/usage", json={"anthropic_admin_key": ""})
    assert client.get("/settings/usage").json()["anthropic_admin_key_set"] is True


def test_usage_endpoint_reports_ledger_spend(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test_leads9.db"))
    import importlib
    import server
    importlib.reload(server)

    server.db_conn.execute(
        "INSERT INTO usage_events (ts, provider, kind, model, requests, input_tokens, "
        "output_tokens, cost_usd) VALUES (replace(datetime('now'), ' ', 'T'), 'anthropic', 'llm', "
        "'claude-sonnet-4-5', 1, 1000, 500, 0.011)"
    )
    server.db_conn.commit()

    body = TestClient(server.app).get("/usage").json()
    assert body["anthropic"]["source"] == "estimated"
    assert body["anthropic"]["spend_usd"] == 0.011
