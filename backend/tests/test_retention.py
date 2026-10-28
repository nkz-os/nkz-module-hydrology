"""Retention simulation: hand-computed expectations, computed independently here."""
import pytest
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


def test_typical_and_dry_year_differ_in_stored_m3_and_summer_days():
    # Soil: cn 80 -> S = 25400/80 - 254 = 63.5 mm, Ia = 0.2 S = 12.7 mm.
    # Bucket: depth 300 mm, fc = 90 mm, wp = 30 mm, available water 60 mm, start 45 mm (25 %).
    # "Summer day with water" = saturation >= 50 % = moisture >= 60 mm. ET0 = 0, so moisture
    # only ever rises, and each year's single storm (Nov 10) decides all 183 days Apr 1..Sep 30.
    # Year rain by index: i<=4 -> 15.05 mm, 5..9 -> 20 mm, >=10 -> 30 mm (21 years).
    # Nearest rank: typical = rank ceil(0.5*21)=11 -> i=10 (30 mm); dry = rank ceil(0.2*21)=5 -> i=4 (15.05 mm).
    # Parcel 1 ha = 10 000 m^2; one design of 100 m^3 (never binding below).
    def storm(i, d):
        if (d.month, d.day) != (11, 10):
            return 0.0
        return 15.05 if i <= 4 else 20.0 if i <= 9 else 30.0

    res = simulate_retention(_history(storm), SOIL, [_design(100.0)], area_ha=1.0)
    assert res.status == "ok" and res.years == 21

    # Typical, P = 30: x = 30 - 12.7 = 17.3; R = 17.3^2 / (17.3 + 63.5) = 299.29 / 80.8 = 3.7040842 mm
    #   captured = 3.7040842 mm * 10 000 m^2 / 1000 = 37.040842 m^3 (< 100)
    #   baseline moisture = 45 + 30 - 3.7040842 = 71.2959 mm (68.8 %) -> 183 summer days
    #   with design = 45 + 3.7040842 + (30 - 3.7040842) = 75.0 mm (75 %) -> 183 days; extra days 0
    assert res.median.season_rain_mm == 30.0
    assert abs(res.median.stored_m3 - 37.040842) < 1e-5
    assert res.median.summer_days_above_threshold == 183
    assert res.median.extra_days_vs_baseline == 0
    assert abs(res.median.extra_m3_vs_baseline - 37.040842) < 1e-5
    assert abs(res.median.season_runoff_mm - 3.7040842) < 1e-6

    # Dry, P = 15.05: x = 2.35; R = 2.35^2 / (2.35 + 63.5) = 5.5225 / 65.85 = 0.0838648 mm
    #   captured = 0.838648 m^3
    #   baseline moisture = 45 + 15.05 - 0.0838648 = 59.9661 mm (49.94 %) -> 0 summer days
    #   with design = 45 + 15.05 = 60.05 mm (50.08 %) -> 183 days; extra days 183
    assert abs(res.dry.season_rain_mm - 15.05) < 1e-9
    assert abs(res.dry.stored_m3 - 0.838648) < 1e-5
    assert res.dry.summer_days_above_threshold == 183
    assert res.dry.extra_days_vs_baseline == 183
    assert abs(res.dry.season_runoff_mm - 0.0838648) < 1e-6

    assert res.median.stored_m3 != res.dry.stored_m3
    assert res.median.extra_days_vs_baseline != res.dry.extra_days_vs_baseline


@pytest.mark.parametrize("area", [0.0, -1.0, float("nan"), None])
def test_invalid_area_is_not_available(area):
    res = simulate_retention(_history(lambda i, d: 1.0), SOIL, [_design(100.0)], area_ha=area)
    assert res.status == "not_available" and res.reason == "parcel area unavailable"
    assert res.median is None and res.dry is None


def test_nan_et0_day_is_treated_as_no_et_and_year_still_counts():
    nan = float("nan")
    base = _history(lambda i, d: 5.0 if (d.month, d.day) == (11, 10) else 0.0, et0=1.0)
    holed = [DailyWater(x.day, x.precip_mm, nan if (x.day.month, x.day.day) == (1, 15) else x.et0_mm)
             for x in base]
    zeroed = [DailyWater(x.day, x.precip_mm, 0.0 if (x.day.month, x.day.day) == (1, 15) else x.et0_mm)
              for x in base]
    a = simulate_retention(holed, SOIL, [_design(100.0)], area_ha=1.0)
    b = simulate_retention(zeroed, SOIL, [_design(100.0)], area_ha=1.0)
    assert a.status == "ok" and a.years == 21
    assert a.median == b.median and a.dry == b.dry


def test_too_many_nan_et0_days_drop_the_years():
    nan = float("nan")
    # every day of Nov and Dec has no ET0: 61 of 365 days (> 10 %) missing in every year
    hist = [DailyWater(x.day, x.precip_mm, nan if x.day.month in (11, 12) else x.et0_mm)
            for x in _history(lambda i, d: 1.0, et0=1.0)]
    res = simulate_retention(hist, SOIL, [], area_ha=1.0)
    assert res.status == "not_available" and res.years == 0
