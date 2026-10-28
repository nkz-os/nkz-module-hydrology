"""Design rainfall statistics (Gumbel annual maxima)."""
from datetime import date, timedelta

import numpy as np

from app.services.design_rain import annual_maxima, design_depth_24h
from app.services.weather_client import DailyWater


def _history(maxima, start_year=2000, missing_frac=0.0, skip_years=()):
    """One hydrological year per maximum; all other days dry (1 mm)."""
    out = []
    for i, m in enumerate(maxima):
        y = start_year + i
        if y in skip_years:
            continue
        d = date(y, 10, 1)
        end = date(y + 1, 10, 1)
        n = 0
        total = (end - d).days
        while d < end:
            n += 1
            gap = n <= int(total * missing_frac)
            val = None if gap else (m if d == date(y + 1, 1, 15) else 1.0)
            out.append(DailyWater(day=d, precip_mm=val, et0_mm=None))
            d += timedelta(days=1)
    return out


def _gumbel(n, mu=40.0, beta=12.0, seed=3):
    return list(np.random.default_rng(seed).gumbel(mu, beta, n))


def test_gumbel_recovers_known_distribution():
    hist = _history(_gumbel(60))
    r = design_depth_24h(hist, 10)
    expected = 1.13 * (40.0 - 12.0 * np.log(-np.log(1 - 1 / 10)))
    assert r.status == "ok"
    assert r.years == 60
    assert abs(r.depth_mm - expected) / expected < 0.05
    assert r.source == "reanalysis"


def test_short_record_not_available():
    r = design_depth_24h(_history(_gumbel(19)), 10)
    assert r.status == "not_available"
    assert r.reason
    assert r.depth_mm is None


def test_empty_history_not_available():
    assert design_depth_24h([], 10).status == "not_available"


def test_incomplete_years_excluded():
    hist = _history(_gumbel(25), skip_years=(2003, 2010))
    assert len(annual_maxima(hist)) == 23
    sparse = _history(_gumbel(3), start_year=2030, missing_frac=0.2)
    assert annual_maxima(sparse) == {}
    # 25 years, 6 of them with 20 % gaps -> 19 complete -> not available
    mixed = _history(_gumbel(19)) + _history(_gumbel(6, seed=1), start_year=2019, missing_frac=0.2)
    assert design_depth_24h(mixed, 10).status == "not_available"


def test_low_confidence_flag_and_interval():
    hist = _history(_gumbel(30))
    r = design_depth_24h(hist, 100)
    assert r.low_confidence is True
    assert r.ci_low_mm < r.depth_mm < r.ci_high_mm
    r10 = design_depth_24h(hist, 10)
    assert r10.low_confidence is False
