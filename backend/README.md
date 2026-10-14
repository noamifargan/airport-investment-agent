# Backend — airport_agent

Python package with the data connectors, deterministic analytics, the Ollama-based agent and the FastAPI server that
also serves `../frontend`. See the [project README](../README.md) for setup and [DESIGN.md](../DESIGN.md) for how it
works.

```bash
uv sync
uv run airport-agent serve     # http://127.0.0.1:8000
uv run pytest
```
