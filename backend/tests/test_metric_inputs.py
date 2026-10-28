"""Parcel KPIs ignore nodata cells and measure stream length on the ground."""
import io
import json

import numpy as np
import pytest
import rasterio

from app.workers import hydrology_worker as hw


def _tif(values, nodata=-9999.0):
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=values.shape[0], width=values.shape[1], count=1,
        dtype="float32", crs="EPSG:25830", nodata=nodata,
        transform=rasterio.transform.from_origin(600000.0, 4700000.0, 2.0, 2.0),
    ) as dst:
        dst.write(values.astype("float32"), 1)
    return buf.getvalue()


def test_metrics_skip_nodata_cells():
    grid = np.full((4, 4), 5.0)
    grid[0, :] = -9999.0
    streams = json.dumps({"type": "FeatureCollection", "features": []}).encode()
    m = hw._compute_metrics({"twi.tif": _tif(grid), "slope.tif": _tif(grid), "streams.geojson": streams})
    assert m["twiMean"] == pytest.approx(5.0)
    assert m["slopeMean"] == pytest.approx(5.0)
    assert m["twiMax"] == pytest.approx(5.0)


def test_stream_length_is_measured_in_metres_on_lon_lat_lines():
    # 0.01 degree of longitude at 42.6 N is about 819 m on the WGS84 ellipsoid.
    line = {"type": "Feature", "geometry": {"type": "LineString",
                                             "coordinates": [[-2.09, 42.6], [-2.08, 42.6]]}}
    gj = json.dumps({"type": "FeatureCollection", "features": [line]}).encode()
    assert hw._stream_length_m(gj) == pytest.approx(819.6, rel=0.01)


def test_weather_takes_rain_from_the_daily_series_even_without_weather_map(monkeypatch):
    from app.services.weather_client import WeatherUnavailable

    class FakeClient:
        def fetch_stats(self, *a, **k):
            raise WeatherUnavailable("down")

        def fetch_daily_water(self, parcel_id, tenant_id, day):
            return 12.5, 1.1

    monkeypatch.setattr(hw, "WeatherClient", FakeClient)
    pw = hw._fetch_weather("urn:ngsi-ld:AgriParcel:p1", "t1", "job")
    assert pw.precipitation_mm == 12.5 and pw.eto_mm == 1.1


def test_weather_is_none_when_every_source_is_down(monkeypatch):
    from app.services.weather_client import WeatherUnavailable

    class Down:
        def fetch_stats(self, *a, **k):
            raise WeatherUnavailable("down")

        def fetch_daily_water(self, *a, **k):
            raise WeatherUnavailable("down")

    monkeypatch.setattr(hw, "WeatherClient", Down)
    assert hw._fetch_weather("p1", "t1", "job") is None
