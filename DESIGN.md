# Airport Investment Intelligence Agent: design

A chat assistant that helps analysts find US airports where terminal expansion would pay off. You ask a question by
typing or speaking. The app pulls public aviation data, scores airports with fixed formulas, and a local AI model
explains the result in plain English.

## 1. High-level design

```
  Browser  (frontend/)                         Server  (backend/)
 ┌───────────────────────┐   question    ┌──────────────────────────────────────────────┐
 │ Web page              │ ────────────► │ API server (FastAPI)                         │
 │ type or speak a       │               │   voice → text: Whisper, runs on the server  │
 │ question, read the    │ ◄──────────── │   agent ──► AI model: Ollama, runs locally   │
 │ answer as it streams  │   answer      │     └────► tools ──► scores and KPIs         │
 └───────────────────────┘               │                        └──► data layer       │
                                         └──────────────────────────────────┬───────────┘
                                                                            │ API calls + disk cache
                                       Public data: BTS, DOT, FAA, OurAirports
```

| Part | What it does | Code |
|---|---|---|
| Web page | Question box, microphone button, answers, scoring panel | `frontend/` |
| API server | Receives questions and recordings, streams answers back | `backend/.../api/app.py` |
| Agent | Understands the question, runs the right analysis, writes the answer | `backend/.../agent/` |
| Scoring | Turns airport facts into 0–100 scores | `backend/.../analytics/` |
| Data layer | Fetches public data through APIs and caches it | `backend/.../data/` |

## 2. How a question is answered

1. **You ask.** Type, or click the microphone and speak. Speech is turned into text on the server.
2. **The app finds the places you mean.** Fixed rules map "LA" to LAX, "Santa Ana" to SNA, and "New England" to six
   states.
3. **The AI picks the analysis.** It chooses one of: rank airports, compare airports, airport profile, route mix,
   unmet demand, or live FAA status. If it doesn't choose, keyword rules pick one instead.
4. **The analysis runs on real data.** Facts and scores are calculated by formulas, not by the AI.
5. **The AI writes the answer** from those results, and is told to quote the numbers exactly. It also gets a short
   skill (`SKILL.md`) for that kind of question (for example, "for unmet demand, lead with passengers per year").
6. **The app adds sources and assumptions** under the answer: which datasets, how fresh, and which caveats apply.
7. **The conversation is remembered**, so follow-ups like "why?" or "how does that compare to LAX?" work.

**Where the data comes from.** Every source is fetched through its public API when needed and saved on disk. If an API
is down, the last saved copy is used and marked as such.

| Source | What it provides |
|---|---|
| BTS T-100 (by airport and by route) | Passengers, seats, flights, freight, distance, for every carrier including cargo |
| BTS On-Time | Delays, taxi times, busiest-hour schedules |
| DOT Airfare Report | Ticket prices by route |
| OurAirports | Airport locations and runway layouts |
| FAA NAS Status | Delay programs and ground stops right now |

## 3. Scoring methodology

Every score is built the same way:

1. **Facts.** Measure each airport: size, growth, how full the planes are, and so on.
2. **Points.** Place each fact on a fixed scale from 0 to 100. For example, planes 70% full score 0 points and 88%
   full score 100. The scales are fixed, so an airport's score doesn't depend on which airports it's compared with.
3. **Weighted score.** Combine the points using fixed weights.

**Rank** sorts airports by their score. **Compare** shows scores side by side and highlights the biggest differences.

### Terminal-expansion score (higher = better investment candidate)

| Fact | Weight | 0 points | 100 points | Why it matters |
|---|---|---|---|---|
| Market size (passengers, last 12 months) | 25% | 100k | 30M | More passengers = more revenue per new gate |
| Passenger growth (year on year) | 20% | −5% | +10% | Demand is rising |
| Load factor (how full the planes are) | 20% | 70% | 88% | Full planes = passengers being turned away |
| Ticket prices vs the US norm for the distance | 10% | −20% | +30% | High fares signal scarce seats |
| Runway room left | 15% | 100% used | 30% used | New gates only pay off if runways can take more flights |
| Number of competing airlines | 10% | one dominant | many | More airlines to fill new gates |

Example: Bradley (BDL) scores **61**. It's a solid market with full planes and plenty of runway room, but passenger
numbers fell 2.3% last year.

### Congestion index (higher = more congested)

| Fact | Weight |
|---|---|
| Busiest-hour flights vs bad-weather runway capacity | 25% |
| Yearly runway use vs estimated capacity | 20% |
| Air-traffic delay minutes per arriving flight | 20% |
| Share of arrivals 15+ minutes late | 15% |
| Average time from gate to take-off | 20% |

### Two supporting estimates

- **Runway capacity** is estimated from runway layout. Runways far apart can work independently; runways close
  together act as one in bad weather. SFO's runway pairs are only 750 ft apart, so its capacity roughly halves in fog.
- **Unmet demand** uses a standard airline "spill" model. From how full the planes are, it estimates how many
  passengers were turned away, then converts that into extra daily flights. SFO comes out at about 1.8M passengers,
  or about 35 flights a day.

If a fact is missing (for example, ticket prices don't exist for Alaska), it's skipped and the other weights are
scaled up. The answer says how much of the score had data behind it.

## 4. Where and how AI is used

| Task | Done by |
|---|---|
| Turning speech into text | AI: Whisper speech model, running on the server |
| Finding airports and regions in the question | Fixed rules |
| Choosing which analysis to run | **AI model** (Ollama, `llama3.1:8b`); keyword rules as a fallback |
| All numbers, scores and rankings | Fixed formulas |
| Writing the answer in plain English | **AI model**, using only the analysis results |
| Off-topic questions, failed analyses | Fixed reply; the AI isn't allowed to improvise |
| Sources and assumptions under each answer | Fixed text from the data, never AI-written |

Both AI models run on the server, so no question, recording or data is sent to an outside AI service, and there's no
per-use cost.

The AI's instructions are plain markdown files in `backend/.../agent/prompts/`: a system prompt, the answer rules, and
one skill folder per kind of question (ranking, comparison, route mix, unmet demand), each with a `SKILL.md` in the
standard skill format: a name and description, then the instructions. A skill is loaded only when its analysis runs, so
the small model reads only the instructions that apply, and analysts can edit them without touching code.

## 5. Key tradeoffs

- **Live data vs speed.** Data comes from public APIs and is saved on disk. The first data pull takes several minutes;
  after that, answers use saved data plus about a minute of AI writing time.
- **Small local AI vs answer quality.** A local 8B model is private and free, but slower and sometimes words a number
  loosely. The numbers themselves are always right, because the AI only explains them and never calculates them. A
  larger model would write better, but rank the same.
- **Fixed scales and weights.** These keep scores stable and comparable, but they're judgement calls. They're shown in
  the app so an analyst can challenge them.
- **Estimated runway capacity.** The app works it out from runway layout for every airport, which is good for screening
  but less precise than the FAA's official rates.
- **No terminal data.** Gate counts and terminal size aren't in the official datasets used here. The score therefore
  measures the *symptoms* of a tight terminal (full planes, high fares, growth), not the terminal itself.
- **Data gaps, stated rather than hidden.** Delay data covers one month and only the larger US airlines and their regional partners. Ticket prices
  exist only for the lower 48 states. Runway use excludes private and military flights.
- **One-day scope.** Simple, readable rules (a fallback router and fixed guards) were chosen over a complex
  multi-step agent.
