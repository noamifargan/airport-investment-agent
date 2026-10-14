"""Runtime settings, read from environment variables (optionally via a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = PACKAGE_DIR / "snapshot"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.1:8b"))
    offline: bool = field(default_factory=lambda: _env_bool("OFFLINE"))
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AIRPORT_AGENT_DATA_DIR", PROJECT_ROOT / "data")).resolve()
    )
    http_timeout: float = field(default_factory=lambda: float(os.environ.get("HTTP_TIMEOUT", "60")))

    @property
    def cache_dir(self) -> Path:
        path = self.data_dir / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
