"""Local speech-to-text for spoken questions (faster-whisper on CPU; audio never leaves the server)."""

from __future__ import annotations

import io
import threading
from functools import lru_cache

import numpy as np

from airport_agent.config import settings

# Biases recognition toward the vocabulary analysts use here (airport codes, place names, metrics).
PROMPT = (
    "Questions about US airports: SFO, LAX, SNA, ANC, BOS, JFK, ORD, BDL, PVD, PWM. "
    "New England, Santa Ana, Anchorage, Logan, terminal expansion, congestion, long-haul, unmet demand, load factor."
)


class VoiceUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _model():
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # optional dependency
        raise VoiceUnavailable("faster-whisper is not installed (uv add faster-whisper)") from exc
    # First call downloads the model from Hugging Face (base.en ≈ 140 MB), then it's cached locally.
    return WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")


def warm_up() -> None:
    """Load the model in the background so the first spoken question isn't slow."""
    threading.Thread(target=lambda: _safe_load(), daemon=True).start()


def _safe_load() -> None:
    try:
        _model()
    except Exception:  # noqa: BLE001 — reported when someone actually uses voice
        pass


def _decode(audio: bytes, rate: int = 16_000) -> np.ndarray:
    """Browser recording (webm/opus, ogg, mp4, wav...) → 16 kHz mono float32, as Whisper expects.

    Done here with PyAV directly because faster-whisper's own decoder passes an argument that
    current PyAV releases no longer accept.
    """
    import av

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            chunks += [f.to_ndarray() for f in resampler.resample(frame)]
        chunks += [f.to_ndarray() for f in resampler.resample(None)]
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks, axis=1).reshape(-1).astype(np.float32) / 32768.0


def transcribe(audio: bytes) -> str:
    """Audio in any common browser format → English text."""
    samples = _decode(audio)
    if samples.size < 1600:  # under 0.1 s: nothing to transcribe
        return ""
    segments, _ = _model().transcribe(samples, language="en", beam_size=1, vad_filter=True, initial_prompt=PROMPT)
    return " ".join(s.text.strip() for s in segments).strip()
