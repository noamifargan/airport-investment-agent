"""Per-airport KPI table built from all connectors (deterministic; no LLM involved)."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd

from airport_agent.analytics import capacity
from airport_agent.data.registry import Registry, set_registry
from airport_agent.data.sources import airfare, ontime, ourairports, t100_origin, t100_segment
from airport_agent.data.store import DataUnavailable, Provenance

MIN_ENPLANEMENTS = 10_000  # FAA "primary commercial service" threshold
LONG_HAUL_MI = 3000  # ≈ 6+ hours block time
DEMAND_CV = 0.30  # flight-level demand variability assumed by the spill model
TARGET_LF = 0.85  # load factor at which new capacity is assumed to be flown


# ------------------------------------------------------------------------------- spill model
def _phi(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _Phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def spill_rate(load_factor: float, cv: float = DEMAND_CV) -> float:
    """Share of passenger demand turned away because flights were full (classic Swan spill model).

    Flight demand D ~ Normal(mu, cv*mu) against capacity 1. Observed load factor = E[min(D, 1)].
    Solve for mu, then spill = E[(D-1)+] / mu.
    """
    if not 0 < load_factor < 1:
        return float("nan")

    def boarded(mu: float) -> tuple[float, float]:
        sigma = cv * mu
        z = (1 - mu) / sigma
        excess = sigma * _phi(z) + (mu - 1) * (1 - _Phi(z))
        return mu - excess, excess

    lo, hi = load_factor, 5.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if boarded(mid)[0] < load_factor else (lo, mid)
    mu = (lo + hi) / 2
    return boarded(mu)[1] / mu


# ------------------------------------------------------------------------------- pieces
def _traffic(monthly: pd.DataFrame) -> pd.DataFrame:
    end = monthly["month"].max()
    t12 = monthly[monthly["month"] > end - pd.DateOffset(months=12)]
    p12 = monthly[(monthly["month"] <= end - pd.DateOffset(months=12)) & (monthly["month"] > end - pd.DateOffset(months=24))]
    y19 = monthly[monthly["month"].dt.year == 2019]
    cols = ["passengers", "departures", "seats", "freight_lbs", "intl_passengers"]
    cur = t12.groupby("iata")[cols].sum()
    out = pd.DataFrame(
        {
            "enplanements_t12m": cur["passengers"],
            "departures_t12m": cur["departures"],
            "seats_t12m": cur["seats"],
            "freight_tons_t12m": cur["freight_lbs"] / 2000,
            "intl_pax_share": cur["intl_passengers"] / cur["passengers"].replace(0, np.nan),
            "load_factor": cur["passengers"] / cur["seats"].replace(0, np.nan),
        }
    )
    out["growth_yoy"] = cur["passengers"] / p12.groupby("iata")["passengers"].sum() - 1
    out["vs_2019"] = cur["passengers"] / y19.groupby("iata")["passengers"].sum() - 1
    out = out.replace([np.inf, -np.inf], np.nan)
    out.attrs["window"] = f"{end - pd.DateOffset(months=11):%Y-%m}..{end:%Y-%m}"
    return out


def _routes(routes: pd.DataFrame) -> pd.DataFrame:
    dep = routes.groupby("origin")
    pax = routes[~routes["cargo"]]
    seats = pax.groupby(["origin", "carrier"])["seats"].sum()
    seats = seats[seats > 0]
    shares = seats / seats.groupby(level="origin").transform("sum")
    hhi = (shares**2).groupby(level="origin").sum()
    top = shares.groupby(level="origin").idxmax().map(lambda t: t[1] if isinstance(t, tuple) else None)
    out = pd.DataFrame(
        {
            "nonstop_destinations": dep["dest"].nunique(),
            "avg_stage_mi": dep.apply(lambda g: np.average(g["distance_mi"], weights=g["departures"])),
            "long_haul_share": dep.apply(lambda g: g.loc[g["distance_mi"] >= LONG_HAUL_MI, "departures"].sum() / g["departures"].sum()),
            "cargo_dep_share": dep.apply(lambda g: g.loc[g["cargo"], "departures"].sum() / g["departures"].sum()),
            "hhi": hhi,
            "top_carrier": top,
            "top_carrier_share": shares.groupby(level="origin").max(),
        }
    )
    return out


def _fares(markets: pd.DataFrame) -> pd.DataFrame:
    """Fare premium = passenger-weighted fare vs a national fare-by-distance curve (log-log fit)."""
    m = markets[(markets["nsmiles"] > 0) & (markets["fare"] > 0)]
    slope, intercept = np.polyfit(np.log(m["nsmiles"]), np.log(m["fare"]), 1, w=np.sqrt(m["passengers"]))
    premium = m["fare"] / np.exp(intercept + slope * np.log(m["nsmiles"])) - 1
    long = pd.concat(
        [
            pd.DataFrame({"iata": m["airport_1"], "premium": premium, "pax": m["passengers"], "fare": m["fare"]}),
            pd.DataFrame({"iata": m["airport_2"], "premium": premium, "pax": m["passengers"], "fare": m["fare"]}),
        ]
    )
    g = long.groupby("iata")
    return pd.DataFrame(
        {
            "fare_premium": g.apply(lambda d: np.average(d["premium"], weights=d["pax"])),
            "avg_fare": g.apply(lambda d: np.average(d["fare"], weights=d["pax"])),
        }
    )


def _capacity(runways: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    rows = {}
    for code, rws in runways[runways["iata"].isin(codes)].groupby("iata"):
        cap = capacity.estimate(rws)
        rows[code] = {
            "vfr_hourly": cap.vfr_hourly or np.nan,
            "ifr_hourly": cap.ifr_hourly or np.nan,
            "asv": cap.asv_annual_ops or np.nan,
            "runway_config": ", ".join(cap.runways_used)
            + (f" (spacing {', '.join(f'{g:,} ft {c}' for g, c in zip(cap.parallel_spacings_ft, cap.spacing_classes))})" if cap.parallel_spacings_ft else ""),
            "runway_note": cap.note,
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def _hub_class(share: float) -> str:
    if share >= 0.01:
        return "Large hub"
    if share >= 0.0025:
        return "Medium hub"
    if share >= 0.0005:
        return "Small hub"
    return "Nonhub"


# ------------------------------------------------------------------------------- assembly
@lru_cache(maxsize=1)
def features() -> tuple[pd.DataFrame, tuple[Provenance, ...]]:
    """One row per US commercial airport with every KPI the scoring and tools use."""
    provs: list[Provenance] = []
    airports, p = ourairports.airports_frame()
    provs.append(p)
    runways, p = ourairports.runways_frame()
    provs.append(p)
    monthly, p = t100_origin.monthly_all()
    provs.append(p)

    traffic = _traffic(monthly)
    us = airports.set_index("iata")
    df = traffic[traffic.index.isin(us.index) & (traffic["enplanements_t12m"] >= MIN_ENPLANEMENTS)].copy()
    df = us.loc[df.index, ["name", "municipality", "state", "lat", "lon"]].join(df)
    df["hub_class"] = (df["enplanements_t12m"] / df["enplanements_t12m"].sum()).map(_hub_class)
    df["annual_ops_est"] = 2 * df["departures_t12m"]

    # Optional sources: a failure leaves those KPI columns empty instead of breaking everything.
    for loader, joiner in [
        (t100_segment.routes_t12m, _routes),
        (airfare.markets_last_4q, _fares),
        (ontime.congestion_latest_month, lambda d: d.set_index("iata")),
    ]:
        try:
            frame, p = loader()
            provs.append(p)
            df = df.join(joiner(frame), how="left")
        except DataUnavailable:
            pass

    df = df.join(_capacity(runways, list(df.index)), how="left")
    df["runway_util"] = df["annual_ops_est"] / df["asv"]
    if "peak_hour_ops" in df:
        df["peak_util_vfr"] = df["peak_hour_ops"] / df["vfr_hourly"]
        df["peak_util_ifr"] = df["peak_hour_ops"] / df["ifr_hourly"]
        df["peak_excess_ifr"] = (df["peak_hour_ops"] - df["ifr_hourly"]).clip(lower=0)

    df["spill_rate"] = df["load_factor"].map(spill_rate)
    df["unmet_pax_t12m"] = df["enplanements_t12m"] * df["spill_rate"] / (1 - df["spill_rate"])
    seats_per_dep = df["seats_t12m"] / df["departures_t12m"].replace(0, np.nan)
    df["unmet_daily_departures"] = df["unmet_pax_t12m"] / (seats_per_dep * TARGET_LF) / 365

    df.index.name = "iata"
    df.attrs["traffic_window"] = traffic.attrs["window"]
    set_registry(Registry(airports, traffic=df["enplanements_t12m"].to_dict()))
    return df, tuple(provs)


@lru_cache(maxsize=1)
def route_table() -> tuple[pd.DataFrame, Provenance]:
    return t100_segment.routes_t12m()
