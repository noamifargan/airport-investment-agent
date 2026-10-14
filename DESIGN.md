# Design — Airport Investment Intelligence Agent

A chat agent that helps analysts find US airports where terminal modernization or expansion would pay off, based on
unmet flight and passenger demand. It pulls public aviation data from government APIs at runtime, scores airports with
deterministic logic, and uses a **local LLM (Ollama)** only to choose tools and explain results.

## 1. Architecture

```
 question ──► Resolver (deterministic) ──► LLM picks tool + args ──► Tools (deterministic) ──► LLM writes answer ──► + footer
              "LA", "Santa Ana",            Ollama, llama3.1:8b       rank / compare / profile     grounded in tool       sources &
              "New England" → codes         (router fallback if       route_mix / unmet_demand     output (KEY FACTS      assumptions
                                             no tool call)             live_status / methodology   first)                 (deterministic)
                                                       │
                                     KPI table (pandas, ~400 commercial airports)
                                                       │
       ┌──────────────┬───────────────────┬────────────┴───────┬───────────────────┬──────────────────┐
   OurAirports   BTS T-100 by airport   BTS T-100 Segment   BTS On-Time        DOT Airfare        FAA NAS Status
   CSV (HTTP)    Socrata API            TranStats download  TranStats ZIP      Socrata API        live XML API
```

**Data layer.** Every source goes through one fetch-with-fallback store (`data/store.py`). The order is:
1. A disk-cache copy that is still within its time-to-live.
2. A **live API call**.
3. If the API is down or `OFFLINE=1`: an expired cached copy, clearly flagged.

Every dataset carries a provenance record (source, URL, pull time, data period, live or cache). That record is printed
under every answer, so the analyst always knows where a number came from and how old it is.

| Source | What it gives | Access | Freshness (as built) |
|---|---|---|---|
| OurAirports | Airport identity, location, runways with end coordinates | HTTP CSV | Nightly |
| BTS T-100 by origin airport (`r495-tyji`) | Monthly passengers, seats, departures, freight per airport, since 2019 | Socrata API | Through 2026-04 |
| BTS T-100 Segment, all carriers | Every route incl. foreign and cargo carriers: departures, seats, distance | TranStats download form (no JSON API exists) | 2025-08..2026-07 |
| BTS Airline On-Time | Per-flight delays, taxi times, scheduled hours (reporting airlines) | Monthly ZIP (~30 MB) | Latest month (2026-07) |
| DOT Airfare Report Table 1a (`tfrh-tu9e`) | Fares by airport pair (contiguous US) | Socrata API | 2025Q2..2026Q1 |
| FAA NAS Status | Ground delay programs, ground stops, closures **right now** | Live XML API | Real time |

Where an API can't provide something, the gap is handled another way and stated:
- **No public API has gate or terminal counts.** Terminal pressure is inferred from load factor, fare premium and growth.
- **No API carries regulatory caps** (e.g. SNA's passenger cap, slot control). These are in a short curated table with
  source references (`analytics/constraints.py`), labelled as static context.
- **OpenSky** flight history requires an account, so it isn't used. BTS T-100 covers the same need with full-year data.

## 2. Scoring methodology (deterministic)

All KPIs come from the sources above and are computed in `analytics/features.py`. Each KPI is mapped linearly onto
0–100 between **fixed anchors**, not the min and max of the current peer set. As a result, an airport's score doesn't
change depending on which airports it's compared with, and scores are comparable across questions. Missing KPIs (e.g.
fares for Alaska) are dropped, the remaining weights are renormalised, and a **coverage** figure (the share of weight
that had data) is reported with every score.

### Terminal-expansion score (0–100, higher = better investment candidate)

| KPI | Weight | 0 points | 100 points | Rationale |
|---|---|---|---|---|
| Market size: enplanements, trailing 12 months (log scale) | 25% | 100k | 30M | Revenue base per added gate |
| Passenger growth: trailing 12 months vs prior 12 | 20% | −5% | +10% | Demand momentum |
| Load factor | 20% | 70% | 88% | Full planes = demand being turned away |
| Fare premium vs national fare-by-distance curve | 10% | −20% | +30% | Scarce seats / pricing power |
| Airside headroom: annual ops ÷ runway annual service volume | 15% | 100% used | 30% used | Gates only pay off if runways can take more flights |
| Carrier diversity: Herfindahl index (HHI) of seat shares | 10% | 0.60 | 0.15 | More airlines competing for new gates; less single-tenant risk |

### Congestion index (0–100, higher = more congested)

| KPI | Weight | 0 points | 100 points |
|---|---|---|---|
| Average daily peak-hour airline operations ÷ bad-weather (IFR) runway capacity | 25% | 50% | 150% |
| Annual runway utilisation (ops ÷ annual service volume) | 20% | 30% | 100% |
| Air-traffic-system (NAS) delay minutes per arrival | 20% | 0 | 15 min |
| Arrivals delayed 15+ min | 15% | 15% | 45% |
| Average taxi-out time | 20% | 10 min | 30 min |

### Supporting models

- **Runway capacity** (`analytics/capacity.py`), planning-level and based on FAA AC 150/5060-5 logic.
  - Only open, paved runways of 5,000 ft or more count.
  - The airport's best family of parallel runways drives capacity, classed by centreline spacing:
    4,300 ft or more is independent; 2,500–4,300 ft is dependent in bad weather; under 2,500 ft acts as one runway in
    bad weather.
  - A single runway gives about 55 operations per hour in good weather (VFR) and 50 in bad weather (IFR).
  - Annual service volume ≈ 3,200 × weather-weighted hourly capacity.
  - Example: SFO's two pairs of runways are about 750 ft apart, giving 120 operations per hour in good weather and only
    65 in bad weather.
- **Unmet demand** uses the classic Swan *spill model*.
  - Demand per flight is assumed to be normally distributed with a coefficient of variation of 0.30. The model solves
    for the mean demand that reproduces the observed load factor.
  - Spilled demand is converted into extra daily departures at an 85% load factor.
  - Peak-hour operations above bad-weather capacity are reported separately as the runway-side shortfall.
- **Long-haul** means 3,000 statute miles or more (about 6+ hours). There's no official definition, so shares at
  2,000, 2,500 and 4,000 miles are always returned for sensitivity, along with the passenger vs cargo split.

## 3. Where AI is used (and where it isn't)

| Step | How |
|---|---|
| Resolving airports, cities and regions ("LA", "Santa Ana", "Logan", "New England") | **Deterministic** registry built from OurAirports data |
| Choosing which tool to call and with which arguments | **LLM** (Ollama tool calling); a keyword **router** takes over if the model makes no call, and bad arguments are repaired with the resolved entities |
| All numbers, rankings, scores and capacity estimates | **Deterministic** Python |
| Key takeaways for each tool result ("KEY FACTS") | **Deterministic**; given to the LLM first so a small model leads with the right facts |
| Explaining the result in plain English, follow-up conversation | **LLM** |
| Sources and assumptions under each answer | **Deterministic** footer, never generated |

The LLM is local (`llama3.1:8b` by default, configurable via `OLLAMA_MODEL`), so no data leaves the machine and there
are no API costs. Conversation memory keeps the last few turns plus a "focus" (the last airports or region discussed).
That's what lets follow-ups like *"Why is Bangor ranked above Boston?"* or *"How does that compare to LAX?"* work.

## 4. Key tradeoffs

- **Live APIs vs speed.** Data is fetched at runtime and cached for a time-to-live set per source: 2 minutes for FAA
  status, 1–30 days for statistics. The first run downloads about 40 MB and takes several minutes; after that, answers
  build from cache in about 3 s plus LLM time.
- **Small local LLM vs answer quality.** An 8B model on CPU takes about 40–75 s per answer and occasionally rephrases a
  number loosely. To compensate:
  - all arithmetic stays in tools;
  - the takeaways are pre-written as KEY FACTS;
  - the model is told to quote numbers verbatim.

  A larger model would write better prose; the rankings would be identical.
- **Fixed anchors vs relative scaling.** Scores are stable and comparable across questions, but the anchors are
  judgement calls. They're listed above and in the `methodology` tool so an analyst can challenge them.
- **Planning-level capacity vs FAA-published rates.** The geometry model works for every airport from public data, but
  it ignores airspace, taxiway layout and crossing-runway interactions. It's suited to screening, not engineering.
- **Proxies for terminal capacity.** Gate and terminal capacity isn't published as data. Load factor, fare premium and
  growth capture the *symptoms* of terminal or airline constraints, not the floor area.
- **Coverage gaps, stated rather than hidden.**
  - On-time data covers one month and only reporting airlines (no cargo or foreign carriers).
  - Fares cover the contiguous US only.
  - Carrier concentration uses operating carriers, so regional partners count separately.
  - Utilisation excludes general aviation (relevant at SNA).

## 5. Example outputs (data as of 2026-10-14)

- **New England terminal expansion:** PWM 68.8, BGR 68.5, BTV 64.5, BDL 61.2, PVD 57.0 (BOS 54.7: biggest market, but
  runways at about 100% of annual capacity).
- **LAX vs SNA congestion:** LAX 42.9 vs SNA 22.4. LAX uses 91% of runway capacity vs 60% at SNA. SNA's binding limit
  is its passenger cap and curfew, not runway congestion.
- **Anchorage long-haul:** 29.5% of 87k departures are 3,000+ mi, driven by cargo (51.6% of cargo flights vs 2.8% of
  passenger flights).
- **SFO unmet demand:** about 1.8M passengers a year (6.5% of demand), about 35 daily departures. The main reason is the
  closely spaced runway pairs, which roughly halve arrival capacity in fog.
