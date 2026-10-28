"""Weather client for hydrology: zonal stats from weather-map, daily rain and ET0
from weather-api.

Service-to-service (namespace ``nekazari``, not behind api-gateway).  Auth is
``X-Tenant-ID`` + ``X-User-ID`` plus the module signature ``X-Auth-Signature``
(platform HMAC over an empty token and the tenant), which weather-map verifies.
Follows the same thin-client pattern as ``dem_client.py``.

Contract reference: AGENTS §8 — precedence meteo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from nkz_platform_sdk.crypto import generate_hmac_signature

from app.config import get_settings

logger = logging.getLogger(__name__)


class WeatherUnavailable(Exception):
    """Weather-map service unreachable or returned error."""


@dataclass(frozen=True)
class ParcelWeather:
    """Zonal weather stats for a parcel on a given date.

    weather-map has no rain metric: ``precipitation_mm`` is filled from
    weather-api's daily series (``fetch_daily_water``), never derived here.
    """
    date: str                         # ISO-8601 date string
    temperature_avg: float | None     # °C
    temperature_min: float | None     # °C
    eto_mm: float | None              # mm/day (reference ET0)
    precipitation_mm: float | None    # mm, last closed day (weather-api)
    soil_moisture: float | None       # m³/m³
    fidelity: str                     # "parcel_weather" | "unavailable"


@dataclass(frozen=True)
class DailyWater:
    """One day of rain and ET0 from weather-api (None where the series has a gap)."""
    day: date
    precip_mm: float | None
    et0_mm: float | None


# Stop reading the history after this many failed years in a row (weather-api down).
MAX_CONSECUTIVE_FAILED_YEARS = 3


# Default metrics requested from weather-map /stats endpoint.
_DEFAULT_METRICS = "temperature_avg,temperature_min,eto,soil_moisture"


class WeatherClient:
    """Thin HTTP client for the weather-map internal service.

    Usage::

        client = WeatherClient()
        pw = client.fetch_stats("urn:ngsi-ld:AgriParcel:p1", "tenant1")
        print(pw.eto_mm)
    """

    def __init__(self, base_url: str | None = None, timeout: float = 15.0,
                 daily_url: str | None = None):
        self._base = (base_url or get_settings().weather_map_url).rstrip("/")
        self._daily = (daily_url or get_settings().weather_api_url).rstrip("/")
        self._timeout = timeout

    @staticmethod
    def _headers(tenant_id: str) -> dict[str, str]:
        headers = {"X-Tenant-ID": tenant_id, "X-User-ID": "hydrology-worker"}
        secret = get_settings().hmac_secret
        if secret:
            headers["X-Auth-Signature"] = generate_hmac_signature(secret, "", tenant_id)
        else:
            logger.warning("weather-map call unsigned: HMAC_SECRET unset")
        return headers

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
        headers = self._headers(tenant_id)
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

        ``precipitation_mm`` stays None: weather-map's ``water_balance`` is a
        5-day sum and cannot be combined with the daily ET0.
        """
        m = body.get("metrics", {})

        def _mean(metric: str) -> float | None:
            v = m.get(metric, {}).get("mean")
            return float(v) if v is not None else None

        return ParcelWeather(
            date=date_label,
            temperature_avg=_mean("temperature_avg"),
            temperature_min=_mean("temperature_min"),
            eto_mm=_mean("eto"),
            precipitation_mm=None,
            soil_moisture=_mean("soil_moisture"),
            fidelity="parcel_weather",
        )

    # ── daily rain and ET0 ────────────────────────────────────────────────

    def fetch_daily_water(
        self, parcel_id: str, tenant_id: str, day: date,
    ) -> tuple[float | None, float | None]:
        """(precip_mm, et0_mm) of one closed day from weather-api's parcel series.

        Gaps in the parcel's own series are filled from Open-Meteo by weather-api.

        Raises:
            WeatherUnavailable: on network error, non-200 status or no row for the day.
        """
        short = parcel_id.rsplit(":", 1)[-1]
        url = f"{self._daily}/api/weather/parcel/{short}/daily"
        params = {"start": day.isoformat(), "end": day.isoformat(), "fill": "open_meteo"}
        try:
            resp = httpx.get(url, params=params, headers=self._headers(tenant_id), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise WeatherUnavailable(f"weather-api unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise WeatherUnavailable(f"weather-api {resp.status_code}: {resp.text[:200]}")
        rows = [d for d in (resp.json() or {}).get("days") or [] if str(d.get("date", ""))[:10] == day.isoformat()]
        if not rows:
            raise WeatherUnavailable(f"weather-api: no daily row for {day.isoformat()}")
        return rows[0].get("precip_mm"), rows[0].get("et0_mm")

    def fetch_daily_history(
        self, parcel_id: str, tenant_id: str, first_year: int, last_year: int,
    ) -> list[DailyWater]:
        """Daily rain and ET0 for ``first_year``..``last_year``, one request per year.

        One request per calendar year keeps each under weather-api's 400-day limit.
        A year that fails is skipped and logged; a year answered with 200 and no
        rows counts as a success with no rows. After
        ``MAX_CONSECUTIVE_FAILED_YEARS`` failures in a row the read stops (a
        success resets the count).

        Raises:
            WeatherUnavailable: when every year failed or the consecutive limit is hit.
        """
        short = parcel_id.rsplit(":", 1)[-1]
        url = f"{self._daily}/api/weather/parcel/{short}/daily"
        out: list[DailyWater] = []
        failed = 0
        consecutive = 0
        years = list(range(first_year, last_year + 1))
        for year in years:
            params = {"start": f"{year}-01-01", "end": f"{year}-12-31", "fill": "open_meteo"}
            try:
                resp = httpx.get(url, params=params, headers=self._headers(tenant_id), timeout=self._timeout)
                if resp.status_code != 200:
                    raise WeatherUnavailable(f"weather-api {resp.status_code}: {resp.text[:200]}")
                rows = (resp.json() or {}).get("days") or []
                year_days = [
                    DailyWater(
                        date.fromisoformat(str(r["date"])[:10]),
                        None if r.get("precip_mm") is None else float(r["precip_mm"]),
                        None if r.get("et0_mm") is None else float(r["et0_mm"]),
                    )
                    for r in rows
                ]
            except (httpx.HTTPError, WeatherUnavailable, ValueError, KeyError, TypeError) as exc:
                failed += 1
                consecutive += 1
                logger.warning("daily history skipped year=%s tenant=%s parcel=%s: %s",
                               year, tenant_id, short, exc)
                if consecutive >= MAX_CONSECUTIVE_FAILED_YEARS:
                    logger.error("daily history aborted after %s consecutive failed years "
                                 "tenant=%s parcel=%s last_error=%s",
                                 consecutive, tenant_id, short, exc)
                    raise WeatherUnavailable(
                        f"weather-api: {consecutive} consecutive years failed: {exc}") from exc
                continue
            consecutive = 0
            out.extend(year_days)
        if years and failed == len(years):
            raise WeatherUnavailable(f"weather-api: daily history failed for all {failed} years")
        return out

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
        headers = self._headers(tenant_id)
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise WeatherUnavailable(f"weather-map forecast unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise WeatherUnavailable(
                f"weather-map forecast {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json().get("forecast", [])
