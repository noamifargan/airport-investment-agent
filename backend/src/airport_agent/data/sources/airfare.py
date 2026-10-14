"""DOT Domestic Airline Consumer Airfare Report, Table 1a — Socrata ``tfrh-tu9e`` on data.transportation.gov.

Quarterly airport-pair markets in the contiguous US (≥10 passengers/day): average fare,
nonstop distance and daily O&D passengers. Alaska and Hawaii are not covered.
"""

from __future__ import annotations

import pandas as pd

from airport_agent.data.socrata import soql
from airport_agent.data.store import DAY, Provenance, fetch_frame

DOMAIN, DATASET = "data.transportation.gov", "tfrh-tu9e"
LABEL = "DOT Consumer Airfare Report Table 1a (data.transportation.gov tfrh-tu9e)"


def _build() -> tuple[pd.DataFrame, dict]:
    latest, _ = soql(DOMAIN, DATASET, {"$select": "year,quarter", "$order": "year DESC, quarter DESC", "$limit": "1"})
    last = int(latest[0]["year"]) * 4 + int(latest[0]["quarter"]) - 1  # quarter index
    first = last - 3
    rows, url = soql(
        DOMAIN,
        DATASET,
        {
            "$select": "year,quarter,airport_1,airport_2,nsmiles,passengers,fare,large_ms",
            "$where": f"year >= '{first // 4}'",
        },
    )
    df = pd.DataFrame(rows)
    for col in ["year", "quarter", "nsmiles", "passengers", "fare", "large_ms"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[(df["year"] * 4 + df["quarter"] - 1).between(first, last)].dropna(subset=["nsmiles", "passengers", "fare"])
    coverage = f"{first // 4}Q{first % 4 + 1}..{last // 4}Q{last % 4 + 1}"
    return df.reset_index(drop=True), {"source": LABEL, "url": url, "coverage": coverage}


def markets_last_4q() -> tuple[pd.DataFrame, Provenance]:
    """Airport-pair markets for the four most recent quarters."""
    return fetch_frame("dot_airfare", "table1a_last4q", _build, ttl=30 * DAY)
