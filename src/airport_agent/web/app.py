"""Minimal web chat: FastAPI backend streaming agent events as NDJSON to a single static page."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from airport_agent.agent.agent import Session, ask
from airport_agent.config import settings

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Airport Investment Intelligence Agent")
SESSIONS: dict[str, Session] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/info")
def info() -> dict:
    return {"model": settings.ollama_model, "offline": settings.offline}


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    sid = req.session_id or uuid.uuid4().hex
    session = SESSIONS.setdefault(sid, Session())

    def events():
        yield json.dumps({"type": "session", "id": sid}) + "\n"
        try:
            for ev in ask(req.message, session):
                yield json.dumps(ev) + "\n"
        except Exception as exc:  # surface errors in the chat instead of a dead stream
            yield json.dumps({"type": "error", "text": f"{type(exc).__name__}: {exc}"}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/reset")
def reset(req: ChatRequest) -> dict:
    SESSIONS.pop(req.session_id or "", None)
    return {"ok": True}
