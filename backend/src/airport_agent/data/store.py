"""Fetch-with-fallback storage layer shared by every data connector.

Every dataset the agent uses is an *artifact*: raw bytes (a CSV, a JSON page, an XML feed)
or a processed table (parquet) produced by a connector's build function. Each artifact is
resolved in this order:

1. ``cache``       — on-disk copy younger than the artifact's TTL
2. ``live``        — fetched from the public API right now (then written to the cache)
3. ``stale_cache`` — the API failed (or OFFLINE=1), so an expired cached copy is served
4. ``snapshot``    — a copy bundled with the package, built from real API pulls at build time

Whatever path wins, the caller gets a :class:`Provenance` describing it, so answers can say
exactly where each number came from and how fresh it is.
"""

from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
import pandas as pd

from airport_agent.config import SNAPSHOT_DIR, settings

log = logging.getLogger(__name__)

USER_AGENT = "airport-agent/0.1 (research prototype; public aviation statistics)"


class DataUnavailable(RuntimeError):
    """Raised when an artifact can't be fetched live and has no cached or bundled copy."""


@dataclass
class Provenance:
    source: str  # human-readable source name, e.g. "BTS T-100 Segment (all carriers)"
    url: str
    fetched_at: str  # ISO timestamp of the original API pull
    mode: str = "live"  # live | cache | stale_cache | snapshot
    coverage: str = ""  # period the data describes, e.g. "2025-05..2026-04"
    note: str = ""
    extra: dict = field(default_factory=dict)

    def age(self) -> str:
        return _age_text(self.fetched_at)

    def short(self) -> str:
        age = _age_text(self.fetched_at)
        cov = f", data {self.coverage}" if self.coverage else ""
        return f"{self.source} [{self.mode}, pulled {age}{cov}]"

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return float("inf")


def _age_text(iso: str) -> str:
    secs = _age_seconds(iso)
    if secs == float("inf"):
        return "at unknown time"
    if secs < 120:
        return "just now"
    if secs < 7200:
        return f"{secs / 60:.0f} min ago"
    if secs < 172800:
        return f"{secs / 3600:.0f} h ago"
    return f"{secs / 86400:.0f} days ago"


# ---------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------

_client: httpx.Client | None = None


def http() -> httpx.Client:
    """Shared HTTP client with connection retries and a polite User-Agent."""
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(settings.http_timeout, connect=15.0),
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=2),
        )
    return _client


def get_with_retry(url: str, *, params: dict | None = None, attempts: int = 3, **kwargs) -> httpx.Response:
    """GET that also retries on 429/5xx (transport retries only cover connection errors)."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = http().get(url, params=params, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------------------------------
# Artifact resolution
# ---------------------------------------------------------------------------------------


def _paths(base: Path, source: str, key: str, ext: str) -> tuple[Path, Path]:
    folder = base / source
    return folder / f"{key}.{ext}", folder / f"{key}.meta.json"


def _read_meta(meta_path: Path) -> dict | None:
    try:
        return json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return None


def _resolve(
    source: str,
    key: str,
    ext: str,
    ttl: float,
    fetch: Callable[[], tuple[bytes, dict]],
) -> tuple[bytes, Provenance]:
    """Core fallback chain. ``fetch`` returns (payload bytes, provenance fields)."""
    data_path, meta_path = _paths(settings.cache_dir, source, key, ext)
    meta = _read_meta(meta_path) if data_path.exists() else None

    if meta and _age_seconds(meta["fetched_at"]) < ttl:
        return data_path.read_bytes(), Provenance(**{**meta, "mode": "cache"})

    error: Exception | None = None
    if not settings.offline:
        try:
            payload, fields = fetch()
            prov = Provenance(fetched_at=_now_iso(), mode="live", **fields)
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_bytes(payload)
            meta_path.write_text(json.dumps({k: v for k, v in prov.to_dict().items() if k != "mode"}, indent=1))
            return payload, prov
        except Exception as exc:  # noqa: BLE001 — any fetch failure falls back
            error = exc
            log.warning("live fetch failed for %s/%s: %s", source, key, exc)

    if meta:
        note = "API unreachable; serving expired cached copy" if error else "OFFLINE mode; cached copy"
        return data_path.read_bytes(), Provenance(**{**meta, "mode": "stale_cache", "note": note})

    snap_path, snap_meta_path = _paths(SNAPSHOT_DIR, source, key, ext)
    snap_meta = _read_meta(snap_meta_path)
    if snap_path.exists() and snap_meta:
        note = "API unreachable; serving bundled snapshot" if error else "OFFLINE mode; bundled snapshot"
        return snap_path.read_bytes(), Provenance(**{**snap_meta, "mode": "snapshot", "note": note})

    raise DataUnavailable(f"{source}/{key}: no live data ({error or 'offline'}) and no cached/bundled copy")


def fetch_bytes(
    source: str,
    key: str,
    url: str,
    *,
    label: str,
    ttl: float,
    ext: str = "bin",
    params: dict | None = None,
    coverage: str = "",
) -> tuple[bytes, Provenance]:
    """Raw HTTP GET artifact (CSV, JSON, XML, ZIP...)."""

    def fetch() -> tuple[bytes, dict]:
        resp = get_with_retry(url, params=params)
        return resp.content, {"source": label, "url": str(resp.url), "coverage": coverage}

    return _resolve(source, key, ext, ttl, fetch)


def fetch_frame(
    source: str,
    key: str,
    build: Callable[[], tuple[pd.DataFrame, dict]],
    *,
    ttl: float,
) -> tuple[pd.DataFrame, Provenance]:
    """Processed-table artifact: ``build`` pulls from APIs and returns (frame, provenance fields)."""

    def fetch() -> tuple[bytes, dict]:
        frame, fields = build()
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        return buf.getvalue(), fields

    payload, prov = _resolve(source, key, "parquet", ttl, fetch)
    return pd.read_parquet(io.BytesIO(payload)), prov


def snapshot_artifact(source: str, key: str, ext: str = "parquet") -> bool:
    """Copy a cached artifact into the bundled snapshot directory (used by `airport-agent snapshot`)."""
    data_path, meta_path = _paths(settings.cache_dir, source, key, ext)
    if not (data_path.exists() and meta_path.exists()):
        return False
    snap_path, snap_meta_path = _paths(SNAPSHOT_DIR, source, key, ext)
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_bytes(data_path.read_bytes())
    snap_meta_path.write_text(meta_path.read_text())
    return True


HOUR = 3600.0
DAY = 24 * HOUR
