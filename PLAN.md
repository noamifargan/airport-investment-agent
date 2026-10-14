# Build plan — Airport Investment Intelligence Agent

Status legend: `[x]` done · `[ ]` pending

Scope rule: one-day build — simplest approach that answers the example questions credibly.

- [x] **0. Data reconnaissance** — verify which public aviation sources are reachable without keys
- [x] **1. Project scaffold** — uv package, `src/` layout, settings, git
- [x] **2. Data foundation** — HTTP client, TTL disk cache, provenance, live → cache → snapshot fallback
- [ ] **3. Connectors**
  - [x] 3a OurAirports — airport registry, regions, runway geometry, name resolver
  - [x] 3b BTS T-100 by origin airport (Socrata `r495-tyji`) — monthly traffic per airport
  - [x] 3c BTS T-100 Segment, all carriers (TranStats) — route-level distance / load factor
  - [x] 3d BTS On-Time Reporting (TranStats PREZIP, latest month) — delays, taxi-out, peak-hour schedule
  - [ ] 3e DOT Consumer Airfare Report Table 1a (Socrata `tfrh-tu9e`) — fares, concentration
  - [ ] 3f FAA NAS Status (live XML) — ground delay programs, ground stops, closures
- [ ] **4. Feature pipeline** — `refresh` builds per-airport KPI table + bundled snapshot
- [ ] **5. Deterministic analytics**
  - [ ] 5a Runway capacity model (parallel spacing → VFR/IFR hourly capacity, ASV)
  - [ ] 5b KPIs (demand, growth, load factor + spill, fare premium, concentration, utilization, congestion, route mix)
  - [ ] 5c Scoring (fixed-anchor 0–100, thesis weights, confidence, sensitivity)
  - [ ] 5d Unit tests on known cases (SFO, SNA, ANC)
- [ ] **6. Agent tools** — rank / compare / profile / route_mix / unmet_demand / live_status / methodology
- [ ] **7. Agent orchestration (Ollama)** — resolver, tool loop, fallback router, grounded answers, memory
- [ ] **8. Chat interface** — FastAPI + web UI (streaming, tables, sources), CLI chat, voice bonus
- [ ] **9. End-to-end evaluation** — the 4 example questions + follow-ups, verify numbers
- [ ] **10. Deliverables** — `DESIGN.md`, `README.md`
