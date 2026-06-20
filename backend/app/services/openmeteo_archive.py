"""
Open-Meteo Archive Client — ERA5 historical daily data.

Direct call to Open-Meteo Archive API (ERA5 reanalysis, not weather-map).
Results cached in Redis by centroid coordinates and year range.

Usage::

    from app.services.openmeteo_archive import fetch_historical_daily

    # Fetch defaults: precipitation, ET0, temperatures
    data = fetch_historical_daily(lat=41.38, lon=2.15)

    # Force refresh, custom variables
    data = fetch_historical_daily(
        lat=41.38, lon=2.15,
        start_year=2000, end_year=2020,
        variables=["temperature_2m_mean", "precipitation_sum"],
        force_refresh=True,
    )
"""

import json
import logging
from datetime import date, timezone
from typing import Optional

import httpx
import redis as sync_redis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Default daily variables (ERA5-based)
DEFAULT_VARIABLES = [
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
]

# Open-Meteo Archive API base
ARCHIVE_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Timeout for the HTTP request
HTTP_TIMEOUT_SECONDS = 30


def _get_redis_client() -> sync_redis.Redis:
    """Create a synchronous Redis client from settings."""
    settings = get_settings()
    return sync_redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )


def _build_cache_key(lat: float, lon: float, start_year: int, end_year: int) -> str:
    """Build a deterministic Redis cache key."""
    return f"omarchive:{lat:.2f}:{lon:.2f}:{start_year}:{end_year}"


def _build_request_url(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    variables: list[str],
) -> str:
    """Build Open-Meteo Archive API URL with daily parameters."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ",".join(variables),
        "timezone": "UTC",
    }
    # Build query string manually to keep it clean
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{ARCHIVE_BASE_URL}?{query}"


def _date_range(
    start_year: int, end_year: int,
) -> tuple[str, str]:
    """Compute start/end date strings for a year range."""
    return (
        f"{start_year}-01-01",
        f"{end_year}-12-31",
    )


def fetch_historical_daily(
    lat: float,
    lon: float,
    start_year: int = 1995,
    end_year: Optional[int] = None,
    variables: Optional[list[str]] = None,
    force_refresh: bool = False,
) -> dict:
    """Fetch historical daily data from Open-Meteo Archive (ERA5).

    Args:
        lat: Latitude (WGS84).
        lon: Longitude (WGS84).
        start_year: First year to fetch (default 1995).
        end_year: Last year to fetch (default current year).
        variables: Daily variable names to request.
            Defaults to precipitation_sum, et0_fao_evapotranspiration,
            temperature_2m_mean, temperature_2m_max, temperature_2m_min.
        force_refresh: If True, skip Redis cache and fetch from API.

    Returns:
        Parsed JSON response dict with keys: latitude, longitude, generationtime_ms,
        utc_offset_seconds, timezone, timezone_abbreviation, elevation,
        daily_units, daily (dict of variable -> list[float]).

    Raises:
        httpx.HTTPError: If the API request fails and no stale cache available.
    """
    if end_year is None:
        end_year = date.today().year

    if variables is None:
        variables = DEFAULT_VARIABLES

    settings = get_settings()
    cache_ttl = settings.openmeteo_cache_ttl_days * 86_400  # seconds

    start_date, end_date = _date_range(start_year, end_year)
    cache_key = _build_cache_key(lat, lon, start_year, end_year)
    r = _get_redis_client()

    # ── Check cache (unless force_refresh) ─────────────────────────
    if not force_refresh:
        cached = r.get(cache_key)
        if cached is not None:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Corrupt cache for %s: %s — refetching", cache_key, exc)

    # ── Fetch from Open-Meteo Archive API ──────────────────────────
    url = _build_request_url(lat, lon, start_date, end_date, variables)
    logger.debug("Fetching Open-Meteo Archive: %s", url)

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        # Cache the result
        r.setex(cache_key, cache_ttl, json.dumps(data))
        return data

    except httpx.HTTPError as exc:
        logger.error("Open-Meteo Archive request failed: %s", exc)

        # Try stale cache as fallback
        stale = r.get(cache_key)
        if stale is not None:
            logger.info("Serving stale cache for %s after HTTP error", cache_key)
            try:
                return json.loads(stale)
            except (json.JSONDecodeError, TypeError):
                pass

        raise
