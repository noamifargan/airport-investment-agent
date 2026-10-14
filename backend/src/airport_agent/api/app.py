"""API server: streams agent events as NDJSON, exposes a few read-only data endpoints, and serves ../frontend."""

from __future__ import annotations

import json
import uuid
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airport_agent.agent.agent import Session, ask
from airport_agent.analytics import scoring
from airport_agent.config import settings
from airport_agent.data.sources import nas_status
from airport_agent.data.store import DataUnavailable

FRONTEND = settings.frontend_dir
app = FastAPI(title="Airport Investment Intelligence")
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")
SESSIONS: dict[str, Session] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/info")
def info() -> dict:
    return {"model": settings.ollama_model, "offline": settings.offline}


@app.get("/api/methodology")
def methodology() -> dict:
    return scoring.methodology()


@app.get("/api/live")
def live() -> dict:
    """Current FAA delay programs, ground stops and delays (closure NOTAMs are counted, not listed)."""
    try:
        events, updated, _ = nas_status.current_events()
    except DataUnavailable:
        return {"available": False, "events": [], "notices": 0, "updated": ""}
    major = [e for e in events if e["type"] != "Closure/restriction NOTAM"]
    return {"available": True, "events": major, "notices": len(events) - len(major), "updated": updated}


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
