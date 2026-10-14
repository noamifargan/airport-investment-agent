"""Planning-level runway capacity from runway geometry (OurAirports runway end coordinates).

Simplified from the logic of FAA AC 150/5060-5 (Airport Capacity and Delay):
* only open, paved runways >= 5,000 ft count (usable by airline jets);
* the airport's capacity is driven by its best family of parallel runways;
* parallel spacing decides how much a second runway adds:
    - >= 4,300 ft apart : independent in all weather
    - 2,500–4,300 ft    : dependent (staggered) in instrument conditions (IFR)
    - 700–2,500 ft      : act as one runway in IFR, two in visual conditions (VFR)  ← SFO's 750 ft pairs
* hourly capacity (mixed arrivals + departures, airline fleet mix):
    single runway ≈ 55 ops/h VFR, 50 ops/h IFR; each extra parallel adds the increments below;
    a usable crossing runway adds a little (+15 VFR / +10 IFR) since it can't run fully independently.
* annual service volume (ASV) ≈ 3,200 × weather-weighted hourly capacity (80% VFR / 20% IFR),
  which reproduces FAA's ballpark ASVs (≈170k single runway, ≈300k close pair, ≈600k LAX-style 4 runways).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

MIN_LENGTH_FT = 5000
PAVED = ("ASP", "CON", "PEM", "BIT", "ASPH", "CONC", "PAVED", "TAR", "BIT")
FT_PER_DEG_LAT = 364_567.0

BASE_VFR, BASE_IFR = 55, 50
ADD_VFR = 50  # each additional parallel >= 700 ft apart (simultaneous visual operations)
ADD_IFR = {"independent": 50, "dependent": 15, "close": 5}
CROSSING_VFR, CROSSING_IFR = 15, 10
MIN_PARALLEL_FT = 650  # FAA minimum for simultaneous VFR ops is 700 ft; allow for coordinate rounding
ASV_PER_WEIGHTED_HOURLY = 3200


@dataclass
class RunwayCapacity:
    runways_used: list[str]
    parallel_spacings_ft: list[int]
    spacing_classes: list[str]
    vfr_hourly: int
    ifr_hourly: int
    asv_annual_ops: int
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _bearing(r: pd.Series) -> float | None:
    if pd.notna(r.le_lat) and pd.notna(r.he_lat):
        dy = r.he_lat - r.le_lat
        dx = (r.he_lon - r.le_lon) * math.cos(math.radians(r.le_lat))
        return math.degrees(math.atan2(dx, dy)) % 180
    if pd.notna(r.le_heading):
        return float(r.le_heading) % 180
    return None


def _spacing_class(ft: float) -> str:
    if ft >= 4300:
        return "independent"
    if ft >= 2500:
        return "dependent"
    return "close"


def estimate(runways: pd.DataFrame) -> RunwayCapacity:
    usable = runways[
        (runways["closed"] == 0)
        & (runways["length_ft"] >= MIN_LENGTH_FT)
        & runways["surface"].str.startswith(PAVED)
    ].copy()
    if usable.empty:
        return RunwayCapacity([], [], [], 0, 0, 0, "no open paved runway >= 5,000 ft")

    usable["bearing"] = usable.apply(_bearing, axis=1)
    usable["name"] = usable["le_ident"] + "/" + usable["he_ident"]
    lat0, lon0 = usable["le_lat"].mean(), usable["le_lon"].mean()

    # Group runways into parallel families (bearings within 10 degrees).
    families: list[list[int]] = []
    for idx, row in usable.iterrows():
        for fam in families:
            b0 = usable.at[fam[0], "bearing"]
            if row.bearing is not None and b0 is not None and min(abs(row.bearing - b0), 180 - abs(row.bearing - b0)) < 10:
                fam.append(idx)
                break
        else:
            families.append([idx])

    best: RunwayCapacity | None = None
    for fam in families:
        rws = usable.loc[fam]
        theta = math.radians(rws["bearing"].dropna().mean() if rws["bearing"].notna().any() else 0)
        # perpendicular offset of each runway's midpoint from the family axis (feet)
        mid_y = ((rws["le_lat"] + rws["he_lat"]) / 2 - lat0) * FT_PER_DEG_LAT
        mid_x = ((rws["le_lon"] + rws["he_lon"]) / 2 - lon0) * math.cos(math.radians(lat0)) * FT_PER_DEG_LAT
        offsets = (mid_x * math.cos(theta) - mid_y * math.sin(theta)).sort_values()
        gaps = offsets.diff().dropna().abs().tolist() if offsets.notna().all() else [1000.0] * (len(rws) - 1)
        gaps = [g for g in gaps if g >= MIN_PARALLEL_FT][:3]  # too close to use simultaneously; cap at 4 runways
        classes = [_spacing_class(g) for g in gaps]
        crossing = len(families) > 1
        vfr = BASE_VFR + ADD_VFR * len(gaps) + (CROSSING_VFR if crossing else 0)
        ifr = BASE_IFR + sum(ADD_IFR[c] for c in classes) + (CROSSING_IFR if crossing else 0)
        asv = round(ASV_PER_WEIGHTED_HOURLY * (0.8 * vfr + 0.2 * ifr), -3)
        cap = RunwayCapacity(list(rws.loc[offsets.index, "name"]), [round(g) for g in gaps], classes, vfr, ifr, int(asv))
        if best is None or (cap.vfr_hourly + cap.ifr_hourly) > (best.vfr_hourly + best.ifr_hourly):
            best = cap
    assert best is not None
    if len(families) > 1:
        best.note = f"{len(families) - 1} crossing runway direction(s) counted as a small bonus only"
    return best
