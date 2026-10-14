"""Agent tools: deterministic functions over the KPI table and live APIs.

Each tool returns ``{"result": ..., "sources": [...], "assumptions": [...]}`` with numbers
already formatted, so the LLM only has to choose a tool and explain — never compute.
"""

from __future__ import annotations

import pandas as pd

from airport_agent.analytics import scoring
from airport_agent.analytics.constraints import KNOWN_CONSTRAINTS
from airport_agent.analytics.features import DEMAND_CV, LONG_HAUL_MI, TARGET_LF, features, route_table
from airport_agent.data.registry import registry
from airport_agent.data.regions import REGIONS
from airport_agent.data.sources import nas_status, t100_origin
from airport_agent.data.store import DataUnavailable


class ToolError(ValueError):
    pass


# --------------------------------------------------------------------------------- helpers
def _pct(v, signed: bool = False) -> str | None:
    return None if pd.isna(v) else (f"{v:+.1%}" if signed else f"{v:.1%}")


def _num(v, unit: str = "", digits: int = 1) -> str | None:
    if pd.isna(v):
        return None
    if abs(v) >= 1e6:
        return f"{v / 1e6:.{digits}f}M{unit}"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.{digits}f}k{unit}"
    return f"{v:.{digits}f}{unit}"


def _codes(airports: list[str] | str) -> list[str]:
    """Resolve codes or names ("Santa Ana", "LA", "KSFO") to IATA codes in the KPI table."""
    df, _ = features()
    items = [airports] if isinstance(airports, str) else list(airports)
    out: list[str] = []
    for item in items:
        item = str(item).strip()
        hits = [item.upper()] if item.upper() in df.index else registry().resolve(item).airports
        if not hits and len(item) == 4 and registry().get(item):
            hits = [registry().get(item).iata]
        if not hits:
            raise ToolError(f"Unknown airport '{item}'. Use an IATA code like SFO or a city name.")
        for code in hits:
            if code not in df.index:
                raise ToolError(f"{code} has no commercial traffic in BTS T-100 (fewer than 10k enplanements).")
            if code not in out:
                out.append(code)
    return out


def _states(region: str) -> tuple[str, list[str]]:
    if region.strip().strip(".").replace(".", "").upper() in {"US", "USA", "UNITED STATES", "NATIONWIDE", "NATIONAL"}:
        return "United States", REGIONS["United States"]
    if region in REGIONS:
        return region, REGIONS[region]
    res = registry().resolve(region)
    if res.states:
        return ", ".join(res.regions), res.states
    if region.strip().upper() in {s for states in REGIONS.values() for s in states}:
        return region.upper(), [region.strip().upper()]
    raise ToolError(f"Unknown region '{region}'. Try a US state, 'New England', 'West Coast', 'Midwest'...")


def _sources(*keys: str) -> list[str]:
    _, provs = features()
    return [p.short() for p in provs if any(k in p.source for k in keys)]


def _kpis(code: str) -> dict:
    df, _ = features()
    r = df.loc[code]
    return {
        "airport": f"{code} — {r['name']} ({r['municipality']}, {r['state']})",
        "hub_class": r["hub_class"],
        "enplanements_12m": _num(r["enplanements_t12m"]),
        "growth_yoy": _pct(r["growth_yoy"], True),
        "vs_2019": _pct(r["vs_2019"], True),
        "load_factor": _pct(r["load_factor"]),
        "fare_premium_vs_us_curve": _pct(r.get("fare_premium"), True),
        "top_carrier": f"{r['top_carrier']} ({r['top_carrier_share']:.0%} of seats)" if pd.notna(r.get("top_carrier_share")) else None,
        "carrier_hhi": None if pd.isna(r.get("hhi")) else round(r["hhi"], 2),
        "runways": r.get("runway_config"),
        "runway_capacity_ops_per_hour": f"{r['vfr_hourly']:.0f} good weather / {r['ifr_hourly']:.0f} bad weather (IFR)" if pd.notna(r.get("vfr_hourly")) else None,
        "annual_ops_est": _num(r["annual_ops_est"], digits=0),
        "runway_utilisation_of_asv": _pct(r.get("runway_util")),
        "peak_hour_airline_ops": None if pd.isna(r.get("peak_hour_ops")) else round(r["peak_hour_ops"]),
        "peak_hour_vs_ifr_capacity": _pct(r.get("peak_util_ifr")),
        "arrivals_delayed_15min": _pct(r.get("arr_delay15_rate")),
        "nas_delay_min_per_arrival": None if pd.isna(r.get("nas_delay_min_per_arr")) else round(r["nas_delay_min_per_arr"], 1),
        "avg_taxi_out_min": None if pd.isna(r.get("avg_taxi_out_min")) else round(r["avg_taxi_out_min"], 1),
        "cancel_rate": _pct(r.get("cancel_rate")),
        "intl_pax_share": _pct(r["intl_pax_share"]),
        "long_haul_departure_share": _pct(r.get("long_haul_share")),
    }


def _assumptions(*topics: str) -> list[str]:
    df, provs = features()
    ontime = next((p for p in provs if "On-Time" in p.source), None)
    fares = next((p for p in provs if "Airfare" in p.source), None)
    text = {
        "traffic": f"Traffic = BTS T-100, all carriers, trailing 12 months {df.attrs['traffic_window']}; "
                   "'enplanements' are departing passengers (total passengers ≈ 2×).",
        "capacity": "Runway capacity is a planning-level estimate from runway geometry (FAA AC 150/5060-5 logic), "
                    "not FAA-published rates; utilisation counts airline + cargo operations only (no GA/military).",
        "ontime": f"Delay, taxi and peak-hour figures come from BTS On-Time {ontime.coverage if ontime else 'n/a'} "
                  "(reporting airlines only — no cargo or foreign carriers), so peak-hour counts are a lower bound "
                  "and reflect a single month's season.",
        "fares": f"Fare premium uses DOT Airfare Table 1a {fares.coverage if fares else 'n/a'} vs a national "
                 "fare-by-distance curve; contiguous US only (no Alaska/Hawaii).",
        "spill": f"Unmet demand = spill model (flight demand variability CV {DEMAND_CV}); extra flights sized at "
                 f"{TARGET_LF:.0%} load factor. It's an order-of-magnitude estimate, not a forecast.",
        "score": "Scores use fixed anchors and weights (see methodology); missing KPIs are dropped and weights "
                 "renormalised — 'coverage' shows the share of weight with data.",
    }
    return [text[t] for t in topics]


# --------------------------------------------------------------------------------- tools
def rank_airports(region: str, metric: str = "terminal_expansion", top_n: int = 10, min_enplanements: int = 100_000) -> dict:
    """Rank commercial airports in a US region/state by terminal-expansion score or congestion index."""
    if metric not in scoring.MODELS:
        metric = "terminal_expansion"
    df, _ = features()
    name, states = _states(region)
    pool = df[df["state"].isin(states) & (df["enplanements_t12m"] >= min_enplanements)]
    if pool.empty:
        raise ToolError(f"No airports in {name} with ≥{min_enplanements:,} annual enplanements.")
    scores = scoring.score_frame(pool, metric).sort_values("score", ascending=False).head(int(top_n))
    ranked = []
    for rank, (code, s) in enumerate(scores.iterrows(), 1):
        detail = scoring.score_row(df.loc[code], metric)
        comps = sorted(detail["components"], key=lambda c: c["points"])
        ranked.append(
            {
                "rank": rank,
                "airport": f"{code} — {df.at[code, 'name']} ({df.at[code, 'state']})",
                "score": s["score"],
                "coverage": s["coverage"],
                "enplanements_12m": _num(df.at[code, "enplanements_t12m"]),
                "strengths": [f"{c['kpi']} {c['value']}" for c in comps[::-1][:2]],
                "weaknesses": [f"{c['kpi']} {c['value']}" for c in comps[:2]],
            }
        )
    excluded = int((df["state"].isin(states) & (df["enplanements_t12m"] < min_enplanements)).sum())
    headline = f"Top candidates in {name} by {metric.replace('_', ' ')} score (0-100): " + ", ".join(
        f"{r['airport'].split(' — ')[0]} {r['score']}" for r in ranked[:5])
    return {
        "result": {"headline": headline, "region": name, "metric": metric, "ranking": ranked,
                   "excluded_small_airports": f"{excluded} airports below {min_enplanements:,} enplanements"},
        "sources": _sources("T-100", "OurAirports", "On-Time", "Airfare"),
        "assumptions": _assumptions("score", "capacity", "ontime" if metric == "congestion" else "fares", "traffic"),
    }


def compare_airports(airports: list[str], metric: str = "congestion") -> dict:
    """Side-by-side KPIs, scores and known constraints for 2+ airports.

    Live FAA status is left out on purpose: a small model confused today's delays with structural constraints.
    """
    if metric not in scoring.MODELS:
        metric = "congestion"
    codes = _codes(airports)
    df, _ = features()
    rows = []
    for code in codes:
        detail = scoring.score_row(df.loc[code], metric)
        rows.append({**_kpis(code), f"{metric}_score": detail["score"], "score_breakdown": detail["components"],
                     "known_constraints": [c["fact"] for c in KNOWN_CONSTRAINTS.get(code, [])]})
    return {
        "result": {"headline": _compare_headline(codes, rows, metric), "metric": metric, "airports": rows},
        "sources": _sources("T-100", "OurAirports", "On-Time", "Airfare"),
        "assumptions": _assumptions("ontime", "capacity", "score", "traffic"),
    }


def _compare_headline(codes: list[str], rows: list[dict], metric: str) -> list[str]:
    """Deterministic takeaways so even a small LLM leads with the right facts."""
    label = "congestion index (0-100, higher = more congested)" if metric == "congestion" else "terminal-expansion score (0-100)"
    order = sorted(zip(codes, rows), key=lambda cr: cr[1][f"{metric}_score"], reverse=True)
    others = ", ".join(c for c, _ in order[1:])
    verdict = "is more congested than" if metric == "congestion" else "is a stronger terminal-expansion candidate than"
    lines = [f"{order[0][0]} {verdict} {others}",
             f"{label}: " + " vs ".join(f"{c} {r[f'{metric}_score']}" for c, r in order)]
    first, last = order[0][1]["score_breakdown"], order[-1][1]["score_breakdown"]
    gaps = []
    for a in first:
        b = next((x for x in last if x["kpi"] == a["kpi"]), None)
        if b:
            gaps.append((abs(a["points"] - b["points"]), f"{a['kpi']}: {order[0][0]} {a['value']} vs {order[-1][0]} {b['value']}"))
    lines += ["biggest difference — " + g for _, g in sorted(gaps, reverse=True)[:3]]
    for c, r in order:
        if r["known_constraints"]:
            lines.append(f"{c} structural constraint: {r['known_constraints'][0]}")
    return lines


def airport_profile(airport: str) -> dict:
    """Everything about one airport: KPIs, both scores, recent monthly trend, live status, constraints."""
    code = _codes(airport)[0]
    df, _ = features()
    result = {
        **_kpis(code),
        "terminal_expansion": scoring.score_row(df.loc[code], "terminal_expansion"),
        "congestion": scoring.score_row(df.loc[code], "congestion"),
        "live_faa_status": _live(code),
        "known_constraints": [c["fact"] for c in KNOWN_CONSTRAINTS.get(code, [])],
    }
    sources = _sources("T-100", "OurAirports", "On-Time", "Airfare") + _live_source()
    try:  # small live query to BTS so the latest months are always current
        monthly, prov = t100_origin.monthly_for(code)
        last = monthly.tail(6)
        result["recent_months_enplanements"] = {f"{m:%Y-%m}": _num(p) for m, p in zip(last["month"], last["passengers"])}
        sources.append(prov.short())
    except DataUnavailable:
        pass
    return {"result": result, "sources": sources, "assumptions": _assumptions("traffic", "capacity", "ontime", "score")}


def route_mix(airport: str, long_haul_miles: int = LONG_HAUL_MI) -> dict:
    """Share of departures by distance band (passenger vs cargo) and the main long-haul routes."""
    code = _codes(airport)[0]
    long_haul_miles = int(long_haul_miles)  # small models often send numbers as strings ("3000")
    routes, prov = route_table()
    r = routes[routes["origin"] == code]
    if r.empty:
        raise ToolError(f"No T-100 segment departures for {code}.")
    total = r["departures"].sum()
    bands = [(0, 500, "under 500 mi"), (500, 1500, "500–1,500 mi"), (1500, long_haul_miles, f"1,500–{long_haul_miles:,} mi"),
             (long_haul_miles, 1e9, f"{long_haul_miles:,}+ mi (long-haul)")]
    mix = {label: _pct(r.loc[(r["distance_mi"] >= lo) & (r["distance_mi"] < hi), "departures"].sum() / total) for lo, hi, label in bands}
    lh = r[r["distance_mi"] >= long_haul_miles]

    def share(mask) -> str | None:
        sub = r[mask]
        return _pct(sub.loc[sub["distance_mi"] >= long_haul_miles, "departures"].sum() / sub["departures"].sum()) if len(sub) else None

    alt = {f"{m:,}+ mi": _pct(r.loc[r["distance_mi"] >= m, "departures"].sum() / total) for m in (2000, 2500, 3000, 4000) if m != long_haul_miles}
    top = (lh.groupby("dest").agg(departures=("departures", "sum"), distance_mi=("distance_mi", "max"), cargo=("cargo", "mean"))
           .sort_values("departures", ascending=False).head(8))
    lh_all, lh_pax, lh_cargo = _pct(lh["departures"].sum() / total), share(~r["cargo"]), share(r["cargo"])
    cargo_share = _pct(r.loc[r["cargo"], "departures"].sum() / total)
    headline = (f"{lh_all} of {code}'s {int(total):,} departures (12 months) are long-haul (≥ {long_haul_miles:,} mi). "
                f"Among cargo flights only, {lh_cargo} are long-haul; among passenger flights only, {lh_pax} are long-haul. "
                f"Cargo flights are {cargo_share} of all departures, so cargo drives the long-haul share.")
    return {
        "result": {
            "headline": headline,
            "airport": _kpis(code)["airport"],
            "departures_12m": int(total),
            "long_haul_definition": f"≥ {long_haul_miles:,} statute miles nonstop (≈ 6+ hours)",
            "long_haul_share_all_flights": _pct(lh["departures"].sum() / total),
            "long_haul_share_passenger_flights": share(~r["cargo"]),
            "long_haul_share_cargo_flights": share(r["cargo"]),
            "cargo_share_of_departures": _pct(r.loc[r["cargo"], "departures"].sum() / total),
            "distance_bands": mix,
            "sensitivity_other_thresholds": alt,
            "top_long_haul_destinations": [
                f"{d}: {int(t.departures):,} deps, {int(t.distance_mi):,} mi, {'mostly cargo' if t.cargo > 0.5 else 'mostly passenger'}"
                for d, t in top.iterrows()
            ],
        },
        "sources": [prov.short()],
        "assumptions": [
            f"BTS T-100 Segment {prov.coverage}: every carrier incl. foreign and all-cargo; departures performed "
            "per nonstop segment, great-circle distance.",
            "'Long-haul' has no single official definition; shares at other cutoffs are listed for sensitivity.",
        ],
    }


def unmet_demand(airport: str) -> dict:
    """Estimate unmet (spilled) passenger and flight demand and explain the drivers."""
    code = _codes(airport)[0]
    df, _ = features()
    r = df.loc[code]
    drivers = []
    if pd.notna(r.get("load_factor")) and r["load_factor"] >= 0.80:
        drivers.append(f"High average load factor ({r['load_factor']:.1%} of seats filled): at this level many "
                       "individual flights are full, so some would-be passengers are turned away.")
    if pd.notna(r.get("peak_util_ifr")) and r["peak_util_ifr"] > 1:
        drivers.append(f"Peak-hour airline schedule ({r['peak_hour_ops']:.0f} ops) exceeds bad-weather runway capacity "
                       f"({r['ifr_hourly']:.0f}/h) — in IFR conditions flights must be held or cancelled.")
    if pd.notna(r.get("runway_util")) and r["runway_util"] > 0.8:
        drivers.append(f"Runways at {r['runway_util']:.0%} of estimated annual capacity — little room to add flights.")
    if pd.notna(r.get("nas_delay_min_per_arr")) and r["nas_delay_min_per_arr"] > 6:
        drivers.append(f"{r['nas_delay_min_per_arr']:.1f} min of airspace/airport (NAS) delay per arrival — congestion, not airline issues.")
    if pd.notna(r.get("fare_premium")) and r["fare_premium"] > 0.08:
        drivers.append(f"Fares {r['fare_premium']:+.0%} vs the national distance curve — scarce seats command a premium.")
    if pd.notna(r.get("hhi")) and r["hhi"] > 0.35:
        drivers.append(f"Concentrated market (HHI {r['hhi']:.2f}) — a dominant carrier may limit capacity growth.")
    for c in KNOWN_CONSTRAINTS.get(code, []):
        drivers.append("Structural: " + c["fact"])
    headline = [
        f"Estimated unmet demand at {code}: about {_num(r['unmet_pax_t12m'])} passengers a year "
        f"({_pct(r['spill_rate'])} of demand), equal to roughly {r['unmet_daily_departures']:.0f} extra daily departures."
    ]
    structural = [d for d in drivers if d.startswith("Structural")]
    headline.append("Main reason: " + (structural[0].removeprefix("Structural: ") if structural else drivers[0] if drivers else "n/a"))
    if pd.notna(r.get("peak_excess_ifr")) and r["peak_excess_ifr"] > 0:
        headline.append(f"In bad weather the average peak hour has {r['peak_excess_ifr']:.0f} more scheduled airline "
                        f"operations than the runways can handle ({r['peak_hour_ops']:.0f} vs {r['ifr_hourly']:.0f}/h).")
    return {
        "result": {
            "headline": headline,
            "airport": _kpis(code)["airport"],
            "unmet_passengers_12m": _num(r["unmet_pax_t12m"]),
            "unmet_share_of_demand": _pct(r["spill_rate"]),
            "extra_daily_departures_needed": None if pd.isna(r["unmet_daily_departures"]) else round(r["unmet_daily_departures"]),
            "peak_hour_ops_above_ifr_capacity": None if pd.isna(r.get("peak_excess_ifr")) else round(r["peak_excess_ifr"]),
            "load_factor": _pct(r["load_factor"]),
            "growth_yoy": _pct(r["growth_yoy"], True),
            "runway_capacity_ops_per_hour": _kpis(code)["runway_capacity_ops_per_hour"],
            "runways": r.get("runway_config"),
            "drivers": drivers or ["No strong capacity-constraint signals in the data."],
            "live_faa_status": _live(code),
        },
        "sources": _sources("T-100", "OurAirports", "On-Time", "Airfare") + _live_source(),
        "assumptions": _assumptions("spill", "capacity", "ontime", "traffic"),
    }


def live_status(airport: str) -> dict:
    """Current FAA delay programs, ground stops and closures for one airport (real time)."""
    code = _codes(airport)[0]
    return {"result": {"airport": code, "events": _live(code)}, "sources": _live_source(), "assumptions": []}


def methodology() -> dict:
    """Scoring KPIs, weights and anchors."""
    return {"result": scoring.methodology(), "sources": [], "assumptions": _assumptions("score", "capacity", "spill")}


def _live(code: str) -> list[str] | str:
    try:
        events, updated, _ = nas_status.events_for(code)
    except DataUnavailable:
        return "FAA NAS Status unavailable"
    return [f"{e['type']}: {e['reason']} ({e['detail']})" for e in events] or [f"No active FAA delay programs ({updated})"]


def _live_source() -> list[str]:
    try:
        return [nas_status.current_events()[2].short()]
    except DataUnavailable:
        return []


TOOLS = {f.__name__: f for f in (rank_airports, compare_airports, airport_profile, route_mix, unmet_demand, live_status, methodology)}

# JSON schemas for Ollama tool calling — kept short so a 4B model picks reliably.
SCHEMAS = [
    {"type": "function", "function": {"name": "rank_airports",
        "description": "Rank airports in a US region or state. metric=terminal_expansion (investment attractiveness) or congestion.",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "string", "description": "e.g. New England, California, West Coast"},
            "metric": {"type": "string", "enum": ["terminal_expansion", "congestion"]}},
            "required": ["region"]}}},
    {"type": "function", "function": {"name": "compare_airports",
        "description": "Compare two or more airports side by side (congestion or terminal_expansion).",
        "parameters": {"type": "object", "properties": {
            "airports": {"type": "array", "items": {"type": "string"}, "description": "IATA codes, e.g. [\"LAX\",\"SNA\"]"},
            "metric": {"type": "string", "enum": ["congestion", "terminal_expansion"]}},
            "required": ["airports"]}}},
    {"type": "function", "function": {"name": "airport_profile",
        "description": "Full profile of one airport: traffic, growth, capacity, scores, live status.",
        "parameters": {"type": "object", "properties": {"airport": {"type": "string"}}, "required": ["airport"]}}},
    {"type": "function", "function": {"name": "route_mix",
        "description": "Share of short/medium/long-haul flights from an airport, passenger vs cargo, top long-haul routes.",
        "parameters": {"type": "object", "properties": {"airport": {"type": "string"},
            "long_haul_miles": {"type": "integer", "description": "threshold, default 3000"}}, "required": ["airport"]}}},
    {"type": "function", "function": {"name": "unmet_demand",
        "description": "Estimate unmet passenger/flight demand at an airport and explain why.",
        "parameters": {"type": "object", "properties": {"airport": {"type": "string"}}, "required": ["airport"]}}},
    {"type": "function", "function": {"name": "live_status",
        "description": "Current FAA delays, ground stops and closures at an airport.",
        "parameters": {"type": "object", "properties": {"airport": {"type": "string"}}, "required": ["airport"]}}},
    {"type": "function", "function": {"name": "methodology",
        "description": "Explain the scoring KPIs, weights and assumptions.",
        "parameters": {"type": "object", "properties": {}}}},
]
