"""OurAirports open data (https://ourairports.com/data/) — airport identity, location and runways.

Public-domain CSVs refreshed nightly, served over HTTP; no API key.
"""

from __future__ import annotations

import io

import pandas as pd

from airport_agent.data.store import DAY, Provenance, fetch_frame, get_with_retry

BASE = "https://davidmegginson.github.io/ourairports-data"
LABEL = "OurAirports"
US_COUNTRIES = {"US", "PR", "VI", "GU", "AS", "MP"}  # states + territories that report to BTS


def _csv(name: str) -> tuple[pd.DataFrame, str]:
    resp = get_with_retry(f"{BASE}/{name}")
    return pd.read_csv(io.BytesIO(resp.content), keep_default_na=False, na_values=[""], low_memory=False), str(resp.url)


def _build_airports() -> tuple[pd.DataFrame, dict]:
    raw, url = _csv("airports.csv")
    df = raw[raw["iso_country"].isin(US_COUNTRIES) & raw["iata_code"].notna() & (raw["type"] != "closed")]
    out = pd.DataFrame(
        {
            "iata": df["iata_code"].str.upper(),
            "ident": df["ident"],
            "name": df["name"],
            "type": df["type"],
            "lat": df["latitude_deg"].astype(float),
            "lon": df["longitude_deg"].astype(float),
            "elevation_ft": pd.to_numeric(df["elevation_ft"], errors="coerce"),
            "state": df["iso_region"].str.split("-").str[-1],
            "country": df["iso_country"],
            "municipality": df["municipality"].fillna(""),
            "scheduled": df["scheduled_service"].eq("yes"),
            "keywords": df["keywords"].fillna(""),
            "wikipedia": df["wikipedia_link"].fillna(""),
        }
    )
    # A handful of IATA codes are duplicated (e.g. a heliport sharing a code) — keep the largest facility.
    type_rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2, "seaplane_base": 3, "heliport": 4}
    out = (
        out.assign(_r=out["type"].map(type_rank).fillna(9), _s=~out["scheduled"])
        .sort_values(["_r", "_s"])
        .drop_duplicates("iata")
        .drop(columns=["_r", "_s"])
        .reset_index(drop=True)
    )
    return out, {"source": LABEL + " airports", "url": url, "coverage": "current"}


def _build_runways() -> tuple[pd.DataFrame, dict]:
    airports, _ = airports_frame()
    raw, url = _csv("runways.csv")
    df = raw[raw["airport_ident"].isin(set(airports["ident"]))].copy()
    df = df.merge(airports[["ident", "iata"]], left_on="airport_ident", right_on="ident", how="left")
    num = lambda c: pd.to_numeric(df[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame(
        {
            "iata": df["iata"],
            "ident": df["airport_ident"],
            "le_ident": df["le_ident"].astype(str),
            "he_ident": df["he_ident"].astype(str),
            "length_ft": num("length_ft"),
            "width_ft": num("width_ft"),
            "surface": df["surface"].fillna("").astype(str).str.upper(),
            "lighted": num("lighted").fillna(0).astype(int),
            "closed": num("closed").fillna(0).astype(int),
            "le_lat": num("le_latitude_deg"),
            "le_lon": num("le_longitude_deg"),
            "he_lat": num("he_latitude_deg"),
            "he_lon": num("he_longitude_deg"),
            "le_heading": num("le_heading_degT"),
        }
    )
    return out.reset_index(drop=True), {"source": LABEL + " runways", "url": url, "coverage": "current"}


def airports_frame() -> tuple[pd.DataFrame, Provenance]:
    """US airports (incl. territories) that have an IATA code."""
    return fetch_frame("ourairports", "us_airports", _build_airports, ttl=30 * DAY)


def runways_frame() -> tuple[pd.DataFrame, Provenance]:
    """Runways (with end coordinates) for every airport in :func:`airports_frame`."""
    return fetch_frame("ourairports", "us_runways", _build_runways, ttl=30 * DAY)
