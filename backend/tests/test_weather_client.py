"""weather-map calls carry the module signature (empty token, bound to the tenant)."""
from __future__ import annotations

import httpx
import pytest
from nkz_platform_sdk.crypto import verify_hmac_signature

from app.config import get_settings
from app.services import weather_client
from app.services.weather_client import WeatherClient, WeatherUnavailable

SECRET = "s3cr3t"


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append({"url": url, "params": params, "headers": headers})
        if url.endswith("/forecast/et0"):
            return httpx.Response(200, json={"forecast": [{"day": 1}]})
        return httpx.Response(200, json={"metrics": {"eto": {"mean": 4.0}}})

    monkeypatch.setattr(weather_client.httpx, "get", fake_get)
    return seen


def _assert_signed(headers):
    assert headers["X-Tenant-ID"] == "t1"
    assert headers["X-User-ID"] == "hydrology-worker"
    assert verify_hmac_signature(SECRET, headers["X-Auth-Signature"], "", "t1")


def test_stats_call_is_signed(secret, calls):
    pw = WeatherClient(base_url="http://wm").fetch_stats("urn:ngsi-ld:AgriParcel:p1", "t1")
    assert pw.eto_mm == 4.0
    _assert_signed(calls[0]["headers"])


def test_forecast_call_is_signed(secret, calls):
    out = WeatherClient(base_url="http://wm").fetch_forecast("urn:ngsi-ld:AgriParcel:p1", "t1")
    assert out == [{"day": 1}]
    _assert_signed(calls[0]["headers"])


def test_rejected_call_raises(secret, monkeypatch):
    monkeypatch.setattr(
        weather_client.httpx, "get", lambda *a, **k: httpx.Response(401, text="no")
    )
    with pytest.raises(WeatherUnavailable):
        WeatherClient(base_url="http://wm").fetch_stats("p1", "t1")


def test_stats_never_reconstruct_precipitation(secret, monkeypatch):
    # weather-map's water_balance is a 5-day sum while eto is daily: adding them
    # gave negative rain. Precipitation comes from weather-api's daily series only.
    body = {"metrics": {"eto": {"mean": 2.35}, "water_balance": {"mean": -8.4}}}
    monkeypatch.setattr(weather_client.httpx, "get", lambda *a, **k: httpx.Response(200, json=body))
    pw = WeatherClient(base_url="http://wm").fetch_stats("urn:ngsi-ld:AgriParcel:p1", "t1")
    assert pw.precipitation_mm is None


def test_daily_water_reads_the_closed_day_from_weather_api(secret, monkeypatch):
    from datetime import date

    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)
        return httpx.Response(200, json={"days": [{"date": "2026-10-27", "precip_mm": 12.5, "et0_mm": 1.1}]})

    monkeypatch.setattr(weather_client.httpx, "get", fake_get)
    out = WeatherClient(base_url="http://wm", daily_url="http://wa").fetch_daily_water(
        "urn:ngsi-ld:AgriParcel:p1", "t1", date(2026, 10, 27))
    assert out == (12.5, 1.1)
    assert seen["url"] == "http://wa/api/weather/parcel/p1/daily"
    assert seen["params"] == {"start": "2026-10-27", "end": "2026-10-27", "fill": "open_meteo"}
    assert verify_hmac_signature(SECRET, seen["headers"]["X-Auth-Signature"], "", "t1")


def test_daily_water_unavailable_raises(secret, monkeypatch):
    from datetime import date

    monkeypatch.setattr(weather_client.httpx, "get", lambda *a, **k: httpx.Response(200, json={"days": []}))
    with pytest.raises(WeatherUnavailable):
        WeatherClient(base_url="http://wm", daily_url="http://wa").fetch_daily_water("p1", "t1", date(2026, 10, 27))
