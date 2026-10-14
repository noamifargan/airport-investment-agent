"""BTS T-100 Segment summary by origin airport — Socrata dataset ``r495-tyji`` on data.bts.gov.

Monthly departures, seats, passengers and freight for every airport, all carriers (US and
foreign), split domestic / outbound-international. Published by BTS ~3–4 months in arrears.
"""

from __future__ import annotations

import pandas as pd

from airport_agent.data.socrata import soql
from airport_agent.data.store import DAY, Provenance, fetch_frame

DOMAIN, DATASET = "data.bts.gov", "r495-tyji"
LABEL = "BTS T-100 by origin airport (data.bts.gov r495-tyji)"
SINCE = "2019-01-01"  # 2019 = last pre-COVID year, used as the recovery baseline

# Socrata column -> our column. The outbound_international_N names are BTS's truncated field names.
COLUMNS = {
    "origin_airport_code": "iata",
    "reporting_month": "month",
    "total_departures": "departures",
    "total_passengers": "passengers",
    "total_seats": "seats",
    "total_freight_lbs": "freight_lbs",
    "total_distance_flight_sm": "avg_distance_mi",
    "domestic_departures": "dom_departures",
    "domestic_passengers": "dom_passengers",
    "outbound_international": "intl_departures",
    "outbound_international_1": "intl_passengers",
    "outbound_international_seats": "intl_seats",
}


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).reindex(columns=list(COLUMNS)).rename(columns=COLUMNS)
    df["month"] = pd.to_datetime(df["month"]).dt.to_period("M").dt.to_timestamp()
    for col in df.columns.difference(["iata", "month"]):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df.sort_values(["iata", "month"]).reset_index(drop=True)


def _coverage(df: pd.DataFrame) -> str:
    return f"{df['month'].min():%Y-%m}..{df['month'].max():%Y-%m}" if len(df) else ""


def _build_all() -> tuple[pd.DataFrame, dict]:
    rows, url = soql(
        DOMAIN,
        DATASET,
        {"$select": ",".join(COLUMNS), "$where": f"reporting_month >= '{SINCE}'", "$order": "reporting_month"},
    )
    df = _frame(rows)
    return df, {"source": LABEL, "url": url, "coverage": _coverage(df)}


def monthly_all() -> tuple[pd.DataFrame, Provenance]:
    """Monthly traffic for every origin airport since 2019 (~80k rows)."""
    return fetch_frame("bts_t100_origin", "all_since_2019", _build_all, ttl=7 * DAY)


def monthly_for(iata: str) -> tuple[pd.DataFrame, Provenance]:
    """Monthly traffic for one airport — a small live query the agent runs per question."""
    code = iata.upper()

    def build() -> tuple[pd.DataFrame, dict]:
        rows, url = soql(
            DOMAIN,
            DATASET,
            {
                "$select": ",".join(COLUMNS),
                "$where": f"origin_airport_code = '{code}' AND reporting_month >= '{SINCE}'",
                "$order": "reporting_month",
            },
        )
        df = _frame(rows)
        return df, {"source": LABEL, "url": url, "coverage": _coverage(df)}

    return fetch_frame("bts_t100_origin", f"airport_{code}", build, ttl=1 * DAY)
