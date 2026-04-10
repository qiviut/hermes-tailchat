from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .broker import broker
from .config import APP_TITLE, DB_PATH, HERMES_API_BASE_URL, HERMES_API_KEY
from .hermes_api import HermesAPIError, HermesClient
from .store import Store
import app.store as store_module


class ConversationCreate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    content: str


store = Store(DB_PATH)
store_module.store = store
hermes = HermesClient(HERMES_API_BASE_URL, HERMES_API_KEY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


async def publish(conversation_id: str, event: dict):
    store.append_run_event(conversation_id, event.get("event", "unknown"), json.dumps(event))
    await broker.publish(conversation_id, event)


async def run_turn(conversation_id: str, assistant_message_id: str, user_message: str) -> None:
    messages = store.get_messages(conversation_id)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["id"] != assistant_message_id
    ]
    conversation_history = history[:-1]
    buffer = ""

    async def on_event(event: dict):
        nonlocal buffer
        kind = event.get("event", "unknown")
        if kind == "message.delta":
            buffer += event.get("delta", "")
            store.update_message(assistant_message_id, buffer, status="streaming")
            await publish(conversation_id, {"event": "message.delta", "message_id": assistant_message_id, "delta": event.get("delta", "")})
            return
        if kind == "run.completed":
            output = event.get("output", "")
            final = output or buffer
            store.update_message(assistant_message_id, final, status="complete")
            await publish(conversation_id, {"event": "message.completed", "message_id": assistant_message_id, "content": final})
            return
        if kind == "run.failed":
            err = event.get("error", "unknown error")
            store.update_message(assistant_message_id, f"[Hermes run failed] {err}", status="error")
            await publish(conversation_id, {"event": "message.error", "message_id": assistant_message_id, "error": err})
            return
        await publish(conversation_id, event)

    try:
        await hermes.run_turn(conversation_id, conversation_history, user_message, on_event)
    except HermesAPIError as exc:
        store.update_message(assistant_message_id, f"[Hermes API error] {exc}", status="error")
        await publish(conversation_id, {"event": "message.error", "message_id": assistant_message_id, "error": str(exc)})
    except Exception as exc:
        store.update_message(assistant_message_id, f"[Unexpected error] {exc}", status="error")
        await publish(conversation_id, {"event": "message.error", "message_id": assistant_message_id, "error": str(exc)})


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")


@app.get("/health")
async def health():
    return {"ok": True, "db_path": str(DB_PATH), "hermes_api_base_url": HERMES_API_BASE_URL}


@app.get("/api/conversations")
async def list_conversations():
    return store.list_conversations()


@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    return store.create_conversation(body.title)


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    return store.get_messages(conversation_id)


@app.post("/api/conversations/{conversation_id}/messages")
async def post_message(conversation_id: str, body: MessageCreate):
    conversations = {c['id'] for c in store.list_conversations()}
    if conversation_id not in conversations:
        raise HTTPException(status_code=404, detail="conversation not found")
    user_msg = store.add_message(conversation_id, "user", body.content, status="complete")
    assistant_msg = store.add_message(conversation_id, "assistant", "", status="queued")
    await publish(conversation_id, {"event": "message.created", "message": user_msg})
    await publish(conversation_id, {"event": "message.created", "message": assistant_msg})
    asyncio.create_task(run_turn(conversation_id, assistant_msg['id'], body.content))
    return {"ok": True, "user_message_id": user_msg['id'], "assistant_message_id": assistant_msg['id']}


@app.get("/api/conversations/{conversation_id}/events")
async def events(conversation_id: str):
    async def stream():
        queue = await broker.subscribe(conversation_id)
        try:
            while True:
                event = await queue.get()
                yield {"data": json.dumps(event)}
        finally:
            await broker.unsubscribe(conversation_id, queue)

    return EventSourceResponse(stream())
