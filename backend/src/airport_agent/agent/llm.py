"""Minimal Ollama chat client (local models; no cloud LLM)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Iterator

import httpx

from airport_agent.config import settings

OPTIONS = {"temperature": 0.2, "num_ctx": 8192}


class LLMUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _thinking_model(model: str) -> bool:
    """Thinking models (e.g. Qwen3-Thinking) must run with think=true so Ollama puts the reasoning in a
    separate field instead of leaking it into the answer; other models must not get the flag."""
    try:
        resp = httpx.post(f"{settings.ollama_host}/api/show", json={"model": model}, timeout=10)
        return "thinking" in (resp.json().get("capabilities") or [])
    except (httpx.HTTPError, ValueError):
        return False


def _body(messages: list[dict], tools: list[dict] | None, stream: bool) -> dict:
    body = {"model": settings.ollama_model, "messages": messages, "stream": stream, "options": OPTIONS}
    if _thinking_model(settings.ollama_model):
        body["think"] = True
    if tools:
        body["tools"] = tools
    return body


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """One non-streaming turn; returns Ollama's ``message`` (may contain ``tool_calls``)."""
    try:
        resp = httpx.post(f"{settings.ollama_host}/api/chat", json=_body(messages, tools, False), timeout=600)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Ollama not reachable at {settings.ollama_host} ({exc})") from exc
    return resp.json()["message"]


def stream(messages: list[dict]) -> Iterator[str]:
    """Stream the answer text token by token."""
    try:
        with httpx.stream("POST", f"{settings.ollama_host}/api/chat", json=_body(messages, None, True), timeout=600) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if text := chunk.get("message", {}).get("content"):
                        yield text
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Ollama not reachable at {settings.ollama_host} ({exc})") from exc
