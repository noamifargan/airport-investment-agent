"""BTS Airline On-Time Performance — per-flight delays and taxi times (TranStats PREZIP files).

One monthly ZIP (~30 MB) covers every domestic flight of the ~15 reporting carriers (all
large US airlines and their regional partners; no cargo, no foreign carriers). We pull the
latest published month and reduce it to a small per-airport congestion table.
"""

from __future__ import annotations

import tempfile
import zipfile

import pandas as pd

from airport_agent.data.store import DAY, Provenance, fetch_frame, http

URL = "https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{y}_{m}.zip"
LABEL = "BTS Airline On-Time Performance (transtats.bts.gov)"
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) airport-agent/0.1"}
COLS = [
    "FlightDate", "Origin", "Dest", "CRSDepTime", "CRSArrTime", "DepDelay", "DepDel15",
    "TaxiOut", "TaxiIn", "ArrDel15", "Cancelled", "NASDelay",
]


def _latest_month() -> tuple[int, int]:
    """Walk back from the current month until BTS has a file (usually ~3 months behind)."""
    month = pd.Timestamp.now().to_period("M")
    for _ in range(8):
        resp = http().head(URL.format(y=month.year, m=month.month), headers=BROWSER_UA)
        if resp.status_code == 200:
            return month.year, month.month
        month -= 1
    raise RuntimeError("no On-Time file found in the last 8 months")


def _aggregate(f: pd.DataFrame) -> pd.DataFrame:
    dep = f.groupby("Origin").agg(
        dep_flights=("Cancelled", "size"),
        cancel_rate=("Cancelled", "mean"),
        dep_delay15_rate=("DepDel15", "mean"),
        avg_dep_delay_min=("DepDelay", "mean"),
        avg_taxi_out_min=("TaxiOut", "mean"),
    )
    arr = f.groupby("Dest").agg(
        arr_flights=("Cancelled", "size"),
        arr_delay15_rate=("ArrDel15", "mean"),
        avg_taxi_in_min=("TaxiIn", "mean"),
        nas_delay_min_total=("NASDelay", "sum"),
    )
    # Scheduled movements per local clock hour: departures at the origin + arrivals at the destination.
    deps = pd.DataFrame({"iata": f["Origin"], "day": f["FlightDate"], "hour": f["CRSDepTime"] // 100})
    arrs = pd.DataFrame({"iata": f["Dest"], "day": f["FlightDate"], "hour": (f["CRSArrTime"] // 100) % 24})
    hourly = pd.concat([deps, arrs]).groupby(["iata", "day", "hour"]).size()
    peak = hourly.groupby(level=["iata", "day"]).max().groupby(level="iata").mean().rename("peak_hour_ops")

    out = dep.join(arr, how="outer").join(peak, how="left")
    out["nas_delay_min_per_arr"] = out["nas_delay_min_total"] / out["arr_flights"]
    out = out.drop(columns="nas_delay_min_total").rename_axis("iata").reset_index()
    return out


def _build() -> tuple[pd.DataFrame, dict]:
    year, month = _latest_month()
    url = URL.format(y=year, m=month)
    with tempfile.TemporaryFile() as tmp:
        with http().stream("GET", url, headers=BROWSER_UA, timeout=600) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes(1 << 20):
                tmp.write(chunk)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            flights = pd.read_csv(zf.open(member), usecols=COLS, low_memory=False)
    out = _aggregate(flights)
    return out, {"source": LABEL, "url": url, "coverage": f"{year}-{month:02d}"}


def congestion_latest_month() -> tuple[pd.DataFrame, Provenance]:
    """Per-airport delay / taxi / peak-hour table for the latest published month."""
    return fetch_frame("bts_ontime", "airport_congestion_latest", _build, ttl=14 * DAY)
