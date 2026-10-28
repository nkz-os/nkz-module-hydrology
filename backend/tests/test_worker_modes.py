"""Worker integration of the calculation modes (all external services mocked)."""
import io
import json
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import rasterio
from botocore.exceptions import ClientError

from app.services import design_cache
from app.services.parcel_settings import ParcelSettings
from app.services.weather_client import DailyWater, WeatherUnavailable

PARCEL = "urn:ngsi-ld:AgriParcel:p-1"
POLY = {"type": "Polygon", "coordinates": [[
    [-1.645, 42.812], [-1.635, 42.812], [-1.635, 42.822], [-1.645, 42.822], [-1.645, 42.812]]]}


def _dem_bytes(cols=60, rows=60):
    z = np.fromfunction(lambda i, j: 100 + abs(j - rows // 2) * 0.5 + i * 0.5,
                        (rows, cols), dtype=np.float32)
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=rows, width=cols, count=1,
                       dtype="float32", crs="EPSG:4258",
                       transform=rasterio.transform.from_origin(-1.645, 42.822, 0.0002, 0.0002)) as dst:
        dst.write(z, 1)
    return buf.getvalue()


def _history(first_year, last_year):
    """Daily history with a distinct annual maximum per year (30..59 mm)."""
    out = []
    d = date(first_year, 1, 1)
    end = date(last_year, 12, 31)
    while d <= end:
        rain = 1.0
        if d.month == 11 and d.day == 15:
            rain = 30.0 + (d.year % 30)
        out.append(DailyWater(d, rain, 2.0))
        d += timedelta(days=1)
    return out


class FakeS3:
    def __init__(self):
        self.store = {}

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = MagicMock()
        body.read.return_value = self.store[Key]
        return {"Body": body}

    def delete_object(self, Bucket, Key):
        self.store.pop(Key, None)

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.store[Key] = Body


def _run(settings, history=None, history_exc=None, s3=None, designs=None):
    from app.services.orion_context_client import SoilContext
    from app.workers.hydrology_worker import run_dem_pipeline

    s3 = s3 if s3 is not None else FakeS3()
    with ExitStack() as st:
        st.enter_context(patch("app.workers.hydrology_worker.DEMClient"))
        st.enter_context(patch("app.workers.hydrology_worker.tile_service"))
        rp = st.enter_context(patch("app.workers.hydrology_worker.records_publish"))
        st.enter_context(patch("app.workers.hydrology_worker._read_parcel_polygon", return_value=(POLY, 5.0)))
        st.enter_context(patch("app.workers.hydrology_worker._reproject_to_utm", return_value=_dem_bytes()))
        st.enter_context(patch("app.workers.hydrology_worker._upload_results"))
        st.enter_context(patch("app.workers.hydrology_worker.extract_zonal_stats", side_effect=lambda z, *a: z))
        st.enter_context(patch("app.workers.hydrology_worker.load_settings", return_value=settings))
        st.enter_context(patch("app.workers.hydrology_worker.SyncOrionClient"))
        st.enter_context(patch("app.workers.hydrology_worker.fetch_parcel_designs", return_value=designs or []))
        st.enter_context(patch("app.services.design_cache.get_s3_client", return_value=s3))
        occ = st.enter_context(patch("app.workers.hydrology_worker.OrionContextClient"))
        wc = st.enter_context(patch("app.workers.hydrology_worker.WeatherClient"))
        rp.publish_hydrology_record = AsyncMock()
        rp.publish_hydrology_zones = AsyncMock()
        ctx = MagicMock()
        ctx.get_soil_context.return_value = SoilContext()
        ctx.get_ndvi_mean.return_value = (0.4, "default")
        occ.return_value.__enter__.return_value = ctx
        client = wc.return_value
        client.fetch_stats.side_effect = WeatherUnavailable("no stats")
        client.fetch_daily_water.return_value = (0.0, 2.0)  # closed day: no rain
        if history_exc is not None:
            client.fetch_daily_history.side_effect = history_exc
        else:
            client.fetch_daily_history.return_value = history
        result = run_dem_pipeline(PARCEL, "job-1", "tenant-a")
        record = rp.publish_hydrology_record.await_args.args[1]
        zones = rp.publish_hydrology_zones.await_args.args[1]
    return result, record, zones, client


def _val(record, name):
    return record[f"nkz:{name}"]["value"]


def _settings(mode="storm", rp=10):
    return ParcelSettings(mode, rp, False, "u", "2026-01-01T00:00:00+00:00")


def _hist():
    last = date.today().year - 1
    return _history(last - 29, last)


def test_storm_mode_uses_design_depth():
    result, record, zones, _ = _run(_settings("storm", 10), history=_hist())
    assert result["status"] == "done"
    assert _val(record, "calculationMode") == "storm"
    assert _val(record, "returnPeriodYears") == 10
    assert _val(record, "designRainStatus") == "ok"
    assert _val(record, "designRainMm") > 30
    assert _val(record, "designRainCiLowMm") < _val(record, "designRainCiHighMm")
    assert "reanalysis" in _val(record, "designRainSource")
    assert "Temez" in _val(record, "designRainSource")
    assert _val(record, "runoffMm") > 0          # 0 mm closed day, still design runoff
    assert _val(record, "peakFlowM3s") > 0
    assert _val(record, "sedimentYieldTonnes") >= 0
    assert _val(record, "soilSaturationPct") >= 0  # saturation keeps the real day
    assert any("nkz:runoffMm" in z and z["nkz:runoffMm"]["value"] > 0 for z in zones)


def test_retention_mode_publishes_retention_fields():
    result, record, _, _ = _run(_settings("retention", 25), history=_hist())
    assert result["status"] == "done"
    assert _val(record, "calculationMode") == "retention"
    assert "nkz:returnPeriodYears" not in record
    assert _val(record, "designRainStatus") == "ok"
    for gone in ("peakFlowM3s", "sedimentYieldTonnes", "pondViability"):
        assert f"nkz:{gone}" not in record
    for name in ("retentionStoredM3", "retentionSummerDays",
                 "retentionDryStoredM3", "retentionDrySummerDays", "runoffMm"):
        assert f"nkz:{name}" in record, name
    assert "nkz:peakFlowM3s" not in record


def test_history_unavailable_publishes_terrain_and_reason():
    result, record, zones, _ = _run(_settings("storm", 10), history_exc=WeatherUnavailable("down"))
    assert result["status"] == "done"
    assert _val(record, "designRainStatus") == "not_available"
    assert _val(record, "designRainReason")
    assert "nkz:designRainMm" not in record
    assert "nkz:runoffMm" not in record and "nkz:peakFlowM3s" not in record
    assert _val(record, "twiMean") is not None and _val(record, "slopeMean") > 0
    assert len(zones) > 0


def test_short_history_is_not_available():
    last = date.today().year - 1
    result, record, _, _ = _run(_settings("storm", 10), history=_history(last - 5, last))
    assert result["status"] == "done"
    assert _val(record, "designRainStatus") == "not_available"
    assert "nkz:designRainMm" not in record


def test_cache_hit_skips_history_fetch():
    s3 = FakeS3()
    _, first, _, c1 = _run(_settings("storm", 10), history=_hist(), s3=s3)
    assert c1.fetch_daily_history.call_count == 1
    _, second, _, c2 = _run(_settings("storm", 10), history=_hist(), s3=s3)
    assert c2.fetch_daily_history.call_count == 0
    assert _val(second, "designRainMm") == _val(first, "designRainMm")
    # another return period misses
    _, _, _, c3 = _run(_settings("storm", 25), history=_hist(), s3=s3)
    assert c3.fetch_daily_history.call_count == 1


def test_cache_key_changes_with_return_period():
    s3 = FakeS3()
    calls = []

    def compute(tag):
        def f():
            calls.append(tag)
            return {"tag": tag}
        return f

    with patch("app.services.design_cache.get_s3_client", return_value=s3):
        a = design_cache.get_or_compute("tenant-a", PARCEL, "storm", 10, 2025, compute("a"))
        b = design_cache.get_or_compute("tenant-a", PARCEL, "storm", 25, 2025, compute("b"))
        c = design_cache.get_or_compute("tenant-a", PARCEL, "storm", 25, 2025, compute("c"))
        d = design_cache.get_or_compute("tenant-a", PARCEL, "storm", 25, 2026, compute("d"))
        e = design_cache.get_or_compute("tenant-a", PARCEL, "retention", 25, 2026, compute("e"))
    assert (a, b, c, d, e) == ({"tag": "a"}, {"tag": "b"}, {"tag": "b"}, {"tag": "d"}, {"tag": "e"})
    assert calls == ["a", "b", "d", "e"]
    assert any(k.endswith("/p-1/design_cache.json") for k in s3.store)


def test_retention_runoff_is_median_year_summed_daily_runoff():
    from app.services.bucket_model import BucketModel
    from app.services.design_rain import _hydro_year
    from app.services.orion_context_client import SoilContext

    hist = _hist()
    soil = SoilContext()
    by_year = {}
    for d in hist:
        by_year.setdefault(_hydro_year(d.day), []).append(d)
    complete = {y: v for y, v in by_year.items() if len(v) >= 360}
    ranked = sorted((sum(i.precip_mm for i in v), y) for y, v in complete.items())
    import math
    median_year = ranked[max(1, math.ceil(0.5 * len(ranked))) - 1][1]
    b = BucketModel(soil.ksat_mmh, soil.field_capacity_vv, soil.wilting_point_vv)
    expected = sum(b.step(i.precip_mm, i.et0_mm, cn=soil.cn)["runoff"] for i in complete[median_year])
    _, record, zones, _ = _run(_settings("retention", 10), history=hist)
    assert expected > 0
    assert _val(record, "runoffMm") == pytest.approx(expected)
    assert all("nkz:peakFlowM3s" not in z and "nkz:sedimentYieldTonnes" not in z
               and "nkz:pondViability" not in z for z in zones)


def test_retention_short_history_not_cached_and_t_not_in_key():
    s3 = FakeS3()
    last = date.today().year - 1
    _, record, _, _ = _run(_settings("retention", 10), history=_history(last - 5, last), s3=s3)
    assert _val(record, "designRainStatus") == "not_available"
    assert not s3.store  # gappy history does not stick
    _, _, _, c1 = _run(_settings("retention", 10), history=_hist(), s3=s3)
    _, _, _, c2 = _run(_settings("retention", 100), history=_hist(), s3=s3)
    assert c1.fetch_daily_history.call_count == 1
    assert c2.fetch_daily_history.call_count == 0


def test_malformed_cache_is_a_miss():
    s3 = FakeS3()
    _run(_settings("storm", 10), history=_hist(), s3=s3)
    (k,) = s3.store
    doc = json.loads(s3.store[k])
    doc["value"] = {"unexpected": 1}
    s3.store[k] = json.dumps(doc).encode()
    _, record, _, client = _run(_settings("storm", 10), history=_hist(), s3=s3)
    assert client.fetch_daily_history.call_count == 1
    assert _val(record, "designRainStatus") == "ok"


def test_unexpected_error_degrades_to_not_available():
    with patch("app.workers.hydrology_worker.design_depth_24h", side_effect=RuntimeError("boom")):
        result, record, zones, _ = _run(_settings("storm", 10), history=_hist())
    assert result["status"] == "done"
    assert _val(record, "designRainStatus") == "not_available"
    assert "RuntimeError" in _val(record, "designRainReason")
    assert "nkz:runoffMm" not in record and len(zones) > 0
