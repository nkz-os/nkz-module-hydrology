"""Weather client for hydrology: fetches zonal stats from weather-map.

Service-to-service (namespace ``nekazari``).  Auth is ``X-Tenant-ID`` +
``X-User-ID`` headers only (weather-map is NOT behind api-gateway; no HMAC,
no JWT).  Follows the same thin-client pattern as ``dem_client.py``.

Contract reference: AGENTS §8 — precedence meteo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WeatherUnavailable(Exception):
    """Weather-map service unreachable or returned error."""


@dataclass(frozen=True)
class ParcelWeather:
    """Zonal weather stats for a parcel on a given date.

    ``precipitation_mm`` is derived from ``water_balance.mean + eto.mean``
    because weather-map exposes ``water_balance`` (= precip − ET0), not raw
    precipitation.
    """
    date: str                         # ISO-8601 date string
    temperature_avg: float | None     # °C
    temperature_min: float | None     # °C
    eto_mm: float | None              # mm/day (reference ET0)
    precipitation_mm: float | None    # mm (reconstructed: wb + et0)
    soil_moisture: float | None       # m³/m³
    fidelity: str                     # "parcel_weather" | "unavailable"


# Default metrics requested from weather-map /stats endpoint.
_DEFAULT_METRICS = "temperature_avg,temperature_min,eto,water_balance,soil_moisture"


class WeatherClient:
    """Thin HTTP client for the weather-map internal service.

    Usage::

        client = WeatherClient()
        pw = client.fetch_stats("urn:ngsi-ld:AgriParcel:p1", "tenant1")
        print(pw.eto_mm)
    """

    def __init__(self, base_url: str | None = None, timeout: float = 15.0):
        self._base = (base_url or get_settings().weather_map_url).rstrip("/")
        self._timeout = timeout

    # ── stats ─────────────────────────────────────────────────────────────

    def fetch_stats(
        self,
        parcel_id: str,
        tenant_id: str,
        metrics: str = _DEFAULT_METRICS,
        date: str | None = None,
    ) -> ParcelWeather:
        """GET /api/weather-map/stats/{parcel_id}?metrics=...

        Returns a ``ParcelWeather`` with the mean values.

        Raises:
            WeatherUnavailable: on network error or non-200 status.
        """
        url = f"{self._base}/api/weather-map/stats/{parcel_id}"
        params: dict[str, str] = {"metrics": metrics}
        if date:
            params["date"] = date
        headers = {"X-Tenant-ID": tenant_id, "X-User-ID": "hydrology-worker"}
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise WeatherUnavailable(f"weather-map unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise WeatherUnavailable(
                f"weather-map {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
        return self._parse_stats(body, date or "latest")

    @staticmethod
    def _parse_stats(body: dict[str, Any], date_label: str) -> ParcelWeather:
        """Extract mean values from the weather-map stats response.

        Response shape::

            { "metrics": { "<metric>": { "mean": ..., ... }, ... } }

        ``precipitation_mm`` is reconstructed: ``water_balance.mean + eto.mean``.
        """
        m = body.get("metrics", {})

        def _mean(metric: str) -> float | None:
            v = m.get(metric, {}).get("mean")
            return float(v) if v is not None else None

        eto = _mean("eto")
        wb = _mean("water_balance")
        # Reconstruct raw precipitation: precip = water_balance + eto
        precip: float | None = None
        if eto is not None and wb is not None:
            precip = wb + eto

        return ParcelWeather(
            date=date_label,
            temperature_avg=_mean("temperature_avg"),
            temperature_min=_mean("temperature_min"),
            eto_mm=eto,
            precipitation_mm=precip,
            soil_moisture=_mean("soil_moisture"),
            fidelity="parcel_weather",
        )

    # ── forecast ──────────────────────────────────────────────────────────

    def fetch_forecast(
        self,
        parcel_id: str,
        tenant_id: str,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """GET /api/weather-map/forecast/et0?parcel_id=...&days=...

        Returns the raw forecast list (``[{day, et0, precip, deficitAfter}]``).

        Raises:
            WeatherUnavailable: on network error or non-200 status.
        """
        url = f"{self._base}/api/weather-map/forecast/et0"
        params = {"parcel_id": parcel_id, "days": str(days)}
        headers = {"X-Tenant-ID": tenant_id, "X-User-ID": "hydrology-worker"}
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise WeatherUnavailable(f"weather-map forecast unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise WeatherUnavailable(
                f"weather-map forecast {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json().get("forecast", [])
