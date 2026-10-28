"""Multi-year daily soil-water simulation for the water-retention mode.

One run per complete hydrological year (October-September), twice: baseline and
with the designs. Routing rules:
  * each day the designs capture that day's runoff volume (runoff_mm * area_m2 / 1000)
    up to their summed capacity; capacity is free again the next day;
  * captured water re-enters the soil that day as extra infiltration spread over the
    parcel (captured_m3 / area_m2 * 1000 mm).
The bucket model is untouched: runoff does not depend on soil moisture, so a throw-away
copy of the bucket is stepped first to read the day's runoff, the captured depth is
added to the real bucket's moisture, and then the real bucket takes the day's step
(its own cap at field capacity and percolation apply). Each year starts from a fresh
bucket so years are independent.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.services.bucket_model import BucketModel
from app.services.design_rain import MIN_COMPLETE_YEARS, MIN_DAY_FRACTION, _hydro_year
from app.services.hydro_record import nkz_attr
from app.services.weather_client import DailyWater

SUMMER_THRESHOLD_PCT = 50.0  # of available water
DRY_PERCENTILE = 0.20
_STORAGE_MONTHS = (10, 11, 12, 1, 2, 3)


@dataclass(frozen=True)
class RetentionYear:
    season_rain_mm: float
    stored_m3: float
    summer_days_above_threshold: int
    extra_m3_vs_baseline: float
    extra_days_vs_baseline: int


@dataclass(frozen=True)
class RetentionResult:
    status: Literal["ok", "not_available"]
    reason: str | None
    median: RetentionYear | None
    dry: RetentionYear | None
    years: int


def _finite(v) -> bool:
    return v is not None and math.isfinite(v)


def _complete_years(history: list[DailyWater]) -> dict[int, list[DailyWater]]:
    """Hydrological years with >= 90 % of days having finite rain AND ET0 (days sorted)."""
    by_year: dict[int, list[DailyWater]] = defaultdict(list)
    for item in history:
        by_year[_hydro_year(item.day)].append(item)
    out: dict[int, list[DailyWater]] = {}
    for year, items in by_year.items():
        n_days = (date(year + 1, 10, 1) - date(year, 10, 1)).days
        ok = [i for i in items if _finite(i.precip_mm) and _finite(i.et0_mm)]
        if len(ok) >= MIN_DAY_FRACTION * n_days:
            out[year] = sorted(items, key=lambda i: i.day)
    return out


def _total_capacity(designs: list[dict]) -> float:
    total = 0.0
    for d in designs:
        cap = nkz_attr(d, "capacity")
        if isinstance(cap, (int, float)) and math.isfinite(cap) and cap > 0:
            total += float(cap)
    return total


def _simulate_year(days, soil, capacity_m3: float, area_m2: float) -> tuple[float, int]:
    """Returns (stored_m3 Oct-Mar, summer days April-Sep at/above threshold)."""
    bucket = BucketModel(soil.ksat_mmh, soil.field_capacity_vv, soil.wilting_point_vv)
    stored = 0.0
    summer = 0
    for item in days:
        p = float(item.precip_mm) if _finite(item.precip_mm) else 0.0
        et0 = float(item.et0_mm) if _finite(item.et0_mm) else 0.0
        if capacity_m3 > 0:
            runoff_mm = copy.copy(bucket).step(p, et0, cn=soil.cn)["runoff"]
            captured_m3 = min(runoff_mm * area_m2 / 1000.0, capacity_m3)
            bucket.moisture += captured_m3 / area_m2 * 1000.0
            if item.day.month in _STORAGE_MONTHS:
                stored += captured_m3
        r = bucket.step(p, et0, cn=soil.cn)
        if 4 <= item.day.month <= 9 and r["saturation_pct"] >= SUMMER_THRESHOLD_PCT:
            summer += 1
    return stored, summer


def _pick(ranked: list[tuple[float, int]], p: float) -> int:
    """Nearest-rank percentile: returns the hydrological year at that rank."""
    rank = max(1, math.ceil(p * len(ranked)))
    return ranked[rank - 1][1]


def simulate_retention(history: list[DailyWater], soil, designs: list[dict], area_ha: float) -> RetentionResult:
    years = _complete_years(history)
    n = len(years)
    if n < MIN_COMPLETE_YEARS:
        return RetentionResult("not_available",
                               f"only {n} complete hydrological years; {MIN_COMPLETE_YEARS} required",
                               None, None, n)
    if not (_finite(area_ha) and area_ha > 0):
        return RetentionResult("not_available", "parcel area unavailable", None, None, n)
    area_m2 = area_ha * 10000.0
    capacity = _total_capacity(designs)

    rain = {y: sum(float(i.precip_mm) for i in days if _finite(i.precip_mm)) for y, days in years.items()}
    ranked = sorted((r, y) for y, r in rain.items())

    def build(year: int) -> RetentionYear:
        base_stored, base_days = _simulate_year(years[year], soil, 0.0, area_m2)
        stored, days_above = _simulate_year(years[year], soil, capacity, area_m2)
        return RetentionYear(
            season_rain_mm=rain[year],
            stored_m3=stored,
            summer_days_above_threshold=days_above,
            extra_m3_vs_baseline=stored - base_stored,
            extra_days_vs_baseline=days_above - base_days,
        )

    return RetentionResult("ok", None, build(_pick(ranked, 0.5)), build(_pick(ranked, DRY_PERCENTILE)), n)
