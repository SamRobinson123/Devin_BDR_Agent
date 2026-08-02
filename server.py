import csv
import io
import json
import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from db import (init_db, list_leads, insert_csv_rows, get_leads_by_ids,
                update_lead_enrichment, upsert_lead, get_setting, set_setting,
                set_phone_source)
import notifications
from nodes.enrich import enrich_node
from nodes.phone import phone_node
from graph import app as compiled_graph

LEADS_DB_PATH = os.getenv("LEADS_DB_PATH", "leads.db")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
db_conn = init_db(LEADS_DB_PATH)


class EnrichRequest(BaseModel):
    lead_ids: list[int]


class ChatRequest(BaseModel):
    message: str
    thread_id: str


class TestNotificationRequest(BaseModel):
    channel: str


def _notification_settings() -> dict:
    return notifications.merge_defaults(
        get_setting(db_conn, notifications.SETTINGS_KEY)
    )


@app.get("/settings/notifications")
def read_notification_settings():
    return notifications.redact(_notification_settings())


@app.put("/settings/notifications")
def write_notification_settings(update: dict):
    merged = notifications.apply_update(_notification_settings(), update)
    set_setting(db_conn, notifications.SETTINGS_KEY, merged)
    return notifications.redact(merged)


@app.post("/settings/notifications/test")
def test_notification(req: TestNotificationRequest):
    settings = _notification_settings()
    subject = "BDR agent test notification"
    body = "If you can read this, the BDR agent can reach you here."
    if req.channel == "slack":
        return notifications.send_slack(settings, f"*{subject}*\n{body}")
    if req.channel == "email":
        return notifications.send_email(settings, subject, body)
    return {"channel": req.channel, "ok": False, "error": "unknown channel"}


@app.get("/leads")
def get_leads(status: str | None = None):
    return list_leads(db_conn, status=status)


@app.post("/leads/upload")
async def upload_leads(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    return insert_csv_rows(db_conn, rows)


@app.post("/leads/enrich")
def enrich_leads(req: EnrichRequest):
    rows = get_leads_by_ids(db_conn, req.lead_ids)
    email_result = enrich_node({"leads": rows})
    phone_result = phone_node({"enriched": email_result["enriched"]})
    for lead in phone_result["enriched"]:
        update_lead_enrichment(
            db_conn, lead["id"], lead.get("email"), lead.get("status"),
            lead.get("phone"), lead.get("phone_status"),
        )
        set_phone_source(db_conn, lead["id"], lead.get("phone_source"))
    return get_leads_by_ids(db_conn, req.lead_ids)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _save_result_to_db(values: dict) -> None:
    for lead in values.get("leads", []):
        upsert_lead(db_conn, {**lead, "source": "chat"})
    for lead in values.get("enriched", []):
        lead_id = upsert_lead(db_conn, {**lead, "source": "chat"})
        update_lead_enrichment(
            db_conn, lead_id, lead.get("email"), lead.get("status"),
            lead.get("phone"), lead.get("phone_status"),
        )
        set_phone_source(db_conn, lead_id, lead.get("phone_source"))


def _notify_gate(payload: dict) -> None:
    settings = _notification_settings()
    if not settings.get("notify_on_gate"):
        return
    notifications.notify(
        settings, "BDR agent needs your call",
        f"{payload['message']}\n\n" + "\n".join(
            notifications.lead_line(lead) for lead in payload.get("leads", [])
        ),
    )


def _build_result(config: dict) -> dict:
    snapshot = compiled_graph.get_state(config)
    values = snapshot.values
    _save_result_to_db(values)

    if snapshot.next:
        interrupt_obj = snapshot.tasks[0].interrupts[0]
        payload = interrupt_obj.value
        _notify_gate(payload)
        return {
            "reply": payload["message"],
            "leads": payload["leads"],
            "paused": True,
            "gate_message": payload["message"],
        }

    return {
        "reply": f"Done. Intent: {values.get('intent')}",
        "leads": values.get("enriched") or values.get("leads"),
        "paused": False,
        "gate_message": None,
    }


def _stream_chat(input_or_command, config: dict):
    for update in compiled_graph.stream(input_or_command, config, stream_mode="updates"):
        node_name = next(iter(update))
        if node_name == "__interrupt__":
            continue
        yield _sse("node", {"node": node_name, "data": update[node_name]})

    yield _sse("result", _build_result(config))


@app.post("/chat")
def chat(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    snapshot = compiled_graph.get_state(config)

    if snapshot.next:
        input_or_command = Command(resume=req.message)
    else:
        input_or_command = {
            "messages": [HumanMessage(content=req.message)], "intent": "",
            "leads": [], "enriched": [], "gate_decision": "",
        }

    return StreamingResponse(
        _stream_chat(input_or_command, config), media_type="text/event-stream"
    )
