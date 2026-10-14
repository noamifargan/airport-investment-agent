# Airport Investment Intelligence Agent

Chat with an AI agent about US airport investment opportunities: which airports are strong candidates for terminal
expansion, how congested they are, their route mix and how much demand goes unmet. The agent pulls public BTS, DOT,
FAA and OurAirports data through their APIs, scores airports deterministically, and runs the LLM locally with
**Ollama**.

See **[DESIGN.md](DESIGN.md)** for the scoring methodology, tradeoffs and where AI is used.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) and internet access to the public APIs.

All commands run from the `backend/` folder:

```bash
ollama pull llama3.1:8b                # default model (any tool-capable Ollama model works)
cd backend
uv sync                                # create the environment
uv run airport-agent refresh           # first data pull, ~40 MB; takes several minutes, then cached
```

## Run

```bash
uv run airport-agent serve             # web chat → http://127.0.0.1:8000 (serves ../frontend)
uv run airport-agent chat              # terminal chat
uv run airport-agent ask "Compare LA and Santa Ana airport congestion levels."
uv run pytest                          # tests
```

Example questions:
- Which airports in New England are strong candidates for terminal expansion?
- Compare LA and Santa Ana airport congestion levels.
- What is the percentage of long haul flights out of Anchorage airport?
- What is the unmet flight demand in SFO airport and why?
- Follow-ups such as *"Why is Bangor ranked above Boston?"* or *"How does that compare to LAX?"*

Each answer shows the tools the agent called, then the answer, then the data sources (with live/cache status and
data period) and the assumptions behind the numbers.

**Voice:** click the microphone next to **Ask**, speak your question, then click it again (Esc cancels). The recording
is transcribed on the server by a local Whisper model (`faster-whisper`, downloaded once, ~140 MB) and asked
automatically. Browsers only allow microphone access on `localhost` or `https` pages.

## Configuration

Set these as environment variables or in `backend/.env` (see `backend/.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.1:8b` | Local model used for tool choice and answers |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `OFFLINE` | `0` | `1` = no network; answer from the disk cache only |
| `AIRPORT_AGENT_DATA_DIR` | `backend/data` | Cache location |
| `AIRPORT_AGENT_FRONTEND_DIR` | `frontend` | Web page the server serves |
| `WHISPER_MODEL` | `base.en` | Local speech-to-text model for voice questions (`small.en` is more accurate, slower) |

## Project layout

```
backend/                     Python project (uv): API server, agent, data, analytics
  src/airport_agent/
    api/app.py               FastAPI: chat stream (NDJSON), voice transcription, scoring weights; serves the frontend
    voice.py                 local speech-to-text (faster-whisper)
    agent/                   tools, Ollama client, agent loop
    analytics/               runway capacity, KPI table, scores, curated constraints
    data/store.py            fetch-with-fallback cache + provenance
    data/sources/            one connector per public source
    data/registry.py         deterministic airport / city / region resolver
    cli.py, config.py        `airport-agent` command and settings
  tests/
  data/cache/                downloaded API data (git-ignored)
frontend/                    static web page, no build step
  index.html
  assets/styles.css, assets/app.js
DESIGN.md, PLAN.md
```
