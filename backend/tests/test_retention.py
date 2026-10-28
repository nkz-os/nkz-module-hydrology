"""Retention simulation: hand-computed expectations, computed independently here."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.services.retention import simulate_retention
from app.services.weather_client import DailyWater

SOIL = SimpleNamespace(cn=80.0, ksat_mmh=50.0, field_capacity_vv=0.30, wilting_point_vv=0.10)
FIRST_YEAR = 2000
N_YEARS = 21


def _days(hy):
    d = date(hy, 10, 1)
    while d < date(hy + 1, 10, 1):
        yield d
        d += timedelta(days=1)


def _history(rain_fn, years=N_YEARS, et0=0.0):
    out = []
    for i in range(years):
        for d in _days(FIRST_YEAR + i):
            out.append(DailyWater(d, rain_fn(i, d), et0))
    return out


def _design(capacity):
    return {"id": "urn:d:1", "nkz:capacity": {"type": "Property", "value": capacity}}


def _scs_runoff(p, cn=80.0):
    s = 25400.0 / cn - 254
    ia = 0.2 * s
    return (p - ia) ** 2 / (p - ia + s) if p > ia else 0.0


def test_median_and_dry_year_match_hand_computation():
    # constant daily rain, rising with the year index; no runoff (cn None)
    soil = SimpleNamespace(cn=None, ksat_mmh=50.0, field_capacity_vv=0.30, wilting_point_vv=0.10)
    hist = _history(lambda i, d: 0.01 * (i + 1))
    res = simulate_retention(hist, soil, [], area_ha=1.0)
    assert res.status == "ok" and res.years == 21
    ndays = lambda i: sum(1 for _ in _days(FIRST_YEAR + i))
    # nearest rank over 21 years: median rank ceil(10.5)=11 -> i=10; dry rank ceil(4.2)=5 -> i=4
    assert abs(res.median.season_rain_mm - 0.01 * 11 * ndays(10)) < 1e-6
    assert abs(res.dry.season_rain_mm - 0.01 * 5 * ndays(4)) < 1e-6
    assert res.median.stored_m3 == 0.0


def test_designs_add_storage_and_days():
    nov = lambda i, d: 50.0 if (d.month, d.day) == (11, 10) else 0.0
    runoff_m3 = _scs_runoff(50.0) * 10000 / 1000  # 1 ha
    res = simulate_retention(_history(nov), SOIL, [_design(100.0)], area_ha=1.0)
    assert abs(res.median.stored_m3 - min(runoff_m3, 100.0)) < 1e-6  # capacity binds
    res2 = simulate_retention(_history(nov), SOIL, [_design(200.0), _design(50.0)], area_ha=1.0)
    assert abs(res2.median.stored_m3 - runoff_m3) < 1e-6  # runoff binds
    assert abs(res2.median.extra_m3_vs_baseline - runoff_m3) < 1e-6

    # April storm: baseline stays just under 50 % of available water, recovered runoff lifts it over
    apr = lambda i, d: 15.01 if (d.month, d.day) == (4, 1) else 0.0
    fc, wp = 0.30 * 300, 0.10 * 300
    base = 0.5 * fc + 15.01 - _scs_runoff(15.01)
    assert (base - wp) / (fc - wp) < 0.5 <= (0.5 * fc + 15.01 - wp) / (fc - wp)
    res3 = simulate_retention(_history(apr), SOIL, [_design(100.0)], area_ha=1.0)
    assert res3.median.summer_days_above_threshold == 183  # Apr 1 .. Sep 30
    assert res3.median.extra_days_vs_baseline == 183


def test_design_without_capacity_adds_nothing():
    nov = lambda i, d: 50.0 if (d.month, d.day) == (11, 10) else 0.0
    for d in ([{"id": "urn:d:1"}], [_design(0)], [_design(None)]):
        res = simulate_retention(_history(nov), SOIL, d, area_ha=1.0)
        assert res.median.stored_m3 == 0.0
        assert res.median.extra_m3_vs_baseline == 0.0
        assert res.median.extra_days_vs_baseline == 0


def test_short_history_not_available():
    res = simulate_retention(_history(lambda i, d: 1.0, years=19), SOIL, [], area_ha=1.0)
    assert res.status == "not_available" and res.reason and res.median is None
    assert res.years == 19
