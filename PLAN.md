# Build plan — Airport Investment Intelligence Agent

Scope rule: one-day build — must-haves only.

- [x] **0. Data reconnaissance** — which public aviation sources are reachable without keys
- [x] **1. Project scaffold** — uv package, settings, git
- [x] **2. Data foundation** — HTTP client, TTL disk cache, provenance, live → cache fallback
- [x] **3. Connectors** — OurAirports, BTS T-100 (by airport + route level), BTS On-Time, DOT Airfare, FAA NAS Status
- [x] **4. Analytics** — runway capacity, per-airport KPIs, deterministic scores, unmet-demand estimate
- [x] **5. Agent** — tools + Ollama tool-calling loop, deterministic fallback, follow-up memory
- [x] **6. Chat interface** — minimal web chat (FastAPI) + CLI chat
- [x] **7. Test** — the 4 example questions + a follow-up
- [ ] **8. Docs** — DESIGN.md (scoring, tradeoffs, where AI is used) + README
