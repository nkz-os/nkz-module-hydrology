"""Design rainfall depths from a parcel's daily rain history.

Method: annual maxima of daily rain per hydrological year (October-September)
fitted with a Gumbel (EV1) distribution by the METHOD OF MOMENTS:
    beta = s * sqrt(6) / pi,   mu = mean - 0.5772 * beta   (Euler gamma),
    x_T  = mu + beta * y_T,    y_T = -ln(-ln(1 - 1/T)).
The 90 % confidence interval is the normal-approximation interval around x_T
using the standard error of the Gumbel quantile (Kite 1977, "Frequency and
Risk Analyses in Hydrology"):
    SE = (s / sqrt(n)) * sqrt(1 + 1.1396 K + 1.1 K^2),  K = (y_T - gamma) * sqrt(6)/pi.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from app.services.weather_client import DailyWater

MIN_COMPLETE_YEARS = 20
MIN_DAY_FRACTION = 0.90
# Daily totals from a fixed observation window (e.g. calendar day) underestimate the
# true maximum 24 h depth; the standard correction is x1.13 (Weiss 1964; WMO Guide to
# Hydrological Practices).
FIXED_TO_24H_FACTOR = 1.13
Z_90 = 1.6449  # two-sided 90 % normal quantile
EULER_GAMMA = 0.5772156649


@dataclass(frozen=True)
class DesignDepth:
    status: Literal["ok", "not_available"]
    reason: str | None
    depth_mm: float | None
    ci_low_mm: float | None
    ci_high_mm: float | None
    years: int
    low_confidence: bool
    source: Literal["reanalysis"] = "reanalysis"


def _hydro_year(d: date) -> int:
    """Hydrological year labelled by the year of its October start."""
    return d.year if d.month >= 10 else d.year - 1


def annual_maxima(history: list[DailyWater]) -> dict[int, float]:
    """Max daily rain per complete hydrological year (>= 90 % of days with a value)."""
    days: dict[int, dict[date, float]] = defaultdict(dict)
    for item in history:
        if item.precip_mm is not None and math.isfinite(item.precip_mm):
            days[_hydro_year(item.day)][item.day] = float(item.precip_mm)
    out: dict[int, float] = {}
    for year, vals in days.items():
        n_days = (date(year + 1, 10, 1) - date(year, 10, 1)).days
        if len(vals) >= MIN_DAY_FRACTION * n_days:
            out[year] = max(vals.values())
    return out


def _na(reason: str, years: int) -> DesignDepth:
    return DesignDepth("not_available", reason, None, None, None, years, False)


def design_depth_24h(history: list[DailyWater], return_period_years: int) -> DesignDepth:
    maxima = annual_maxima(history)
    n = len(maxima)
    if n < MIN_COMPLETE_YEARS:
        return _na(f"only {n} complete hydrological years; {MIN_COMPLETE_YEARS} required", n)
    if return_period_years < 2:
        return _na("return period must be at least 2 years", n)
    x = np.array(list(maxima.values()), dtype=float)
    s = float(np.std(x, ddof=1))
    beta = s * math.sqrt(6.0) / math.pi
    mu = float(np.mean(x)) - EULER_GAMMA * beta
    y = -math.log(-math.log(1.0 - 1.0 / return_period_years))
    quantile = mu + beta * y
    k = (y - EULER_GAMMA) * math.sqrt(6.0) / math.pi
    se = (s / math.sqrt(n)) * math.sqrt(max(1.0 + 1.1396 * k + 1.1 * k * k, 0.0))
    f = FIXED_TO_24H_FACTOR
    return DesignDepth(
        status="ok",
        reason=None,
        depth_mm=f * quantile,
        ci_low_mm=max(f * (quantile - Z_90 * se), 0.0),
        ci_high_mm=f * (quantile + Z_90 * se),
        years=n,
        low_confidence=return_period_years > 2 * n,
    )
