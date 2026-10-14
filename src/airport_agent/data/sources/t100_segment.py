"""BTS T-100 Segment (All Carriers) — route-level traffic from the TranStats download service.

Every nonstop segment flown by US and foreign carriers (passenger *and* cargo), per month:
departures performed, seats, passengers, freight, great-circle distance and service class.
TranStats has no JSON API for this table, so the connector drives its public download form
(an ASP.NET page: GET for the form state, POST with the selected fields → ZIP of CSV).

Service classes: F = scheduled passenger/cargo, G = scheduled all-cargo,
L = non-scheduled (charter) passenger/cargo, P = non-scheduled all-cargo.
"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile

import pandas as pd

from airport_agent.data.store import DAY, Provenance, fetch_frame, http

FORM_URL = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"
LABEL = "BTS T-100 Segment, all carriers (transtats.bts.gov)"
FIELDS = [
    "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE", "UNIQUE_CARRIER",
    "ORIGIN", "ORIGIN_COUNTRY", "DEST", "DEST_COUNTRY", "YEAR", "MONTH", "CLASS",
]
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) airport-agent/0.1"}
CARGO_CLASSES = {"G", "P"}

log = logging.getLogger(__name__)


def _download_year(year: int, attempts: int = 3) -> pd.DataFrame:
    """All months of ``year`` that BTS has published (one POST, ~6 MB zip / ~90 s for a full year).

    TranStats intermittently answers with its error page, so retry with fresh form state.
    """
    for attempt in range(1, attempts + 1):
        try:
            return _post_year(year)
        except RuntimeError as exc:
            log.warning("TranStats T-100 %s attempt %d/%d failed: %s", year, attempt, attempts, exc)
            http().cookies.clear()
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def _post_year(year: int) -> pd.DataFrame:
    page = http().get(FORM_URL, headers=BROWSER_UA)
    page.raise_for_status()
    form = {
        name: (m.group(1) if (m := re.search(rf'id="{name}" value="([^"]*)"', page.text)) else "")
        for name in ("__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS", "__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
    }
    form |= {"cboGeography": "All", "cboYear": str(year), "cboPeriod": "All", "btnDownload": "Download"}
    form |= {field: "on" for field in FIELDS}
    resp = http().post(FORM_URL, data=form, headers=BROWSER_UA, timeout=600, follow_redirects=False)
    if resp.status_code != 200 or resp.content[:2] != b"PK":
        raise RuntimeError(f"TranStats returned HTTP {resp.status_code} ({resp.headers.get('location', 'no zip')})")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        return pd.read_csv(zf.open(member), low_memory=False)


def _build_t12m() -> tuple[pd.DataFrame, dict]:
    year = pd.Timestamp.now().year
    try:
        frames = [_download_year(year)]
    except RuntimeError:
        frames = []  # early in the year BTS may not have published any month yet
    if sum(len(f) for f in frames) == 0:
        frames = [_download_year(year - 1)]
    months = lambda: pd.concat(frames)[["YEAR", "MONTH"]].drop_duplicates().shape[0]  # noqa: E731
    if months() < 12:
        frames.append(_download_year(int(frames[0]["YEAR"].min()) - 1))
    raw = pd.concat(frames, ignore_index=True)
    raw["period"] = pd.to_datetime(dict(year=raw["YEAR"], month=raw["MONTH"], day=1))
    end = raw["period"].max()
    start = end - pd.DateOffset(months=11)
    raw = raw[(raw["period"] >= start) & (raw["DEPARTURES_PERFORMED"] > 0)]
    if raw["period"].nunique() != 12:
        raise RuntimeError(f"T-100 window {start:%Y-%m}..{end:%Y-%m} has only {raw['period'].nunique()} months")

    routes = (
        raw.groupby(["ORIGIN", "DEST", "UNIQUE_CARRIER", "CLASS"], as_index=False)
        .agg(
            departures=("DEPARTURES_PERFORMED", "sum"),
            seats=("SEATS", "sum"),
            passengers=("PASSENGERS", "sum"),
            freight_lbs=("FREIGHT", "sum"),
            distance_mi=("DISTANCE", "max"),
            origin_country=("ORIGIN_COUNTRY", "first"),
            dest_country=("DEST_COUNTRY", "first"),
            months=("period", "nunique"),
        )
        .rename(columns={"ORIGIN": "origin", "DEST": "dest", "UNIQUE_CARRIER": "carrier", "CLASS": "service_class"})
    )
    routes["cargo"] = routes["service_class"].isin(CARGO_CLASSES)
    coverage = f"{start:%Y-%m}..{end:%Y-%m}"
    return routes, {"source": LABEL, "url": FORM_URL, "coverage": coverage}


def routes_t12m() -> tuple[pd.DataFrame, Provenance]:
    """Trailing-12-month route table: one row per (origin, dest, carrier, service class)."""
    return fetch_frame("bts_t100_segment", "routes_t12m", _build_t12m, ttl=7 * DAY)
