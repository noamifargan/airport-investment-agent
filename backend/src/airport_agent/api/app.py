"""API server: streams agent events as NDJSON, exposes the scoring weights, and serves ../frontend."""

from __future__ import annotations

import json
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airport_agent.agent.agent import Session, ask
from airport_agent.analytics import scoring
from airport_agent import voice
from airport_agent.config import settings

FRONTEND = settings.frontend_dir
app = FastAPI(title="Airport Investment Intelligence")
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")
SESSIONS: dict[str, Session] = {}
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@app.on_event("startup")
def _warm_voice() -> None:
    voice.warm_up()


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


@app.post("/api/transcribe")
async def transcribe(request: Request) -> dict:
    """Spoken question (raw audio body from the browser's recorder) → text, using local Whisper."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio received.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long; keep questions under about a minute.")
    try:
        text = await run_in_threadpool(voice.transcribe, audio)
    except voice.VoiceUnavailable as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:  # undecodable or corrupt recording
        raise HTTPException(400, f"Couldn't read the recording ({type(exc).__name__}).") from exc
    return {"text": text}


@app.post("/api/reset")
def reset(req: ChatRequest) -> dict:
    SESSIONS.pop(req.session_id or "", None)
    return {"ok": True}
