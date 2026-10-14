"""Deterministic 0–100 scores with fixed anchors (no LLM; same inputs → same ranking).

Each KPI is mapped linearly onto 0–100 between two *fixed* anchors (not min/max of the current
peer set), so an airport's score doesn't change depending on who it's compared with. Missing
KPIs are dropped and the remaining weights renormalised; ``coverage`` reports how much of the
model's weight had data, which feeds the confidence statement in every answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Component:
    key: str  # KPI column in the features table
    label: str
    weight: float
    lo: float  # value that scores 0
    hi: float  # value that scores 100 (lo > hi means "lower is better")
    fmt: str  # how to print the raw value
    why: str


# Terminal-expansion attractiveness: is there demand a bigger terminal could capture profitably?
TERMINAL_EXPANSION = [
    Component("enplanements_t12m", "Market size", 0.25, 5.0, 7.48, "{:,.0f} enplanements",
              "log10 scale: 100k → 0, 30M → 100; bigger base = more revenue per added gate"),
    Component("growth_yoy", "Passenger growth (YoY)", 0.20, -0.05, 0.10, "{:+.1%}",
              "trailing-12-month vs prior 12 months: −5% → 0, +10% → 100"),
    Component("load_factor", "Load factor (demand pressure)", 0.20, 0.70, 0.88, "{:.1%}",
              "full planes = demand spilling; 70% → 0, 88% → 100"),
    Component("fare_premium", "Fare premium vs national curve", 0.10, -0.20, 0.30, "{:+.1%}",
              "fares above the distance-adjusted US average signal scarce capacity / pricing power"),
    Component("runway_util", "Airside headroom", 0.15, 1.00, 0.30, "{:.0%} of runway ASV used",
              "terminal gates only pay off if runways can take more flights: 100% used → 0, 30% → 100"),
    Component("hhi", "Carrier diversity", 0.10, 0.60, 0.15, "HHI {:.2f}",
              "many carriers = more tenants competing for new gates; HHI 0.60 → 0, 0.15 → 100"),
]

# Congestion index: how stretched is the airport today (higher = more congested)?
CONGESTION = [
    Component("peak_util_ifr", "Peak hour vs bad-weather capacity", 0.25, 0.5, 1.5, "{:.0%}",
              "scheduled airline ops in the average daily peak hour ÷ IFR runway capacity"),
    Component("runway_util", "Annual runway utilisation", 0.20, 0.30, 1.00, "{:.0%} of ASV",
              "annual air-carrier operations ÷ annual service volume"),
    Component("nas_delay_min_per_arr", "System (NAS) delay per arrival", 0.20, 0.0, 15.0, "{:.1f} min",
              "delay minutes attributed to airport/airspace congestion, per arriving flight"),
    Component("arr_delay15_rate", "Arrivals delayed 15+ min", 0.15, 0.15, 0.45, "{:.0%}", ""),
    Component("avg_taxi_out_min", "Average taxi-out time", 0.20, 10.0, 30.0, "{:.1f} min",
              "ground congestion between gate and runway"),
]

MODELS = {"terminal_expansion": TERMINAL_EXPANSION, "congestion": CONGESTION}


def _points(c: Component, value: float) -> float:
    if c.key == "enplanements_t12m":
        value = math.log10(max(value, 1.0))
    frac = (value - c.lo) / (c.hi - c.lo)
    return max(0.0, min(100.0, 100.0 * frac))


def score_row(row: pd.Series, model: str = "terminal_expansion") -> dict:
    comps = MODELS[model]
    parts, missing = [], []
    for c in comps:
        value = row.get(c.key)
        if value is None or pd.isna(value):
            missing.append(c.label)
            continue
        parts.append({"kpi": c.label, "value": c.fmt.format(value), "points": round(_points(c, value)), "weight": c.weight})
    used = sum(p["weight"] for p in parts)
    total = sum(p["points"] * p["weight"] for p in parts) / used if used else float("nan")
    for p in parts:
        p["weight"] = round(p["weight"] / used, 3)
    return {"score": round(total, 1), "coverage": round(used, 2), "components": parts, "missing": missing}


def score_frame(df: pd.DataFrame, model: str = "terminal_expansion") -> pd.DataFrame:
    rows = {code: score_row(r, model) for code, r in df.iterrows()}
    return pd.DataFrame(
        {
            "score": {k: v["score"] for k, v in rows.items()},
            "coverage": {k: v["coverage"] for k, v in rows.items()},
        }
    )


def methodology() -> dict:
    return {
        name: [{"kpi": c.label, "weight": c.weight, "scale": c.why or f"{c.lo} → 0, {c.hi} → 100"} for c in comps]
        for name, comps in MODELS.items()
    }
