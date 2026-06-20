"""Tests for Open-Meteo Archive client."""

from unittest.mock import MagicMock, patch

import pytest

try:
    import redis as sync_redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


# Sample API response mimicking Open-Meteo Archive format
SAMPLE_API_RESPONSE = {
    "latitude": 41.38,
    "longitude": 2.15,
    "generationtime_ms": 0.5,
    "utc_offset_seconds": 0,
    "timezone": "UTC",
    "timezone_abbreviation": "UTC",
    "elevation": 10.0,
    "daily_units": {
        "time": "iso8601",
        "precipitation_sum": "mm",
        "et0_fao_evapotranspiration": "mm",
        "temperature_2m_mean": "°C",
        "temperature_2m_max": "°C",
        "temperature_2m_min": "°C",
    },
    "daily": {
        "time": ["2023-01-01", "2023-01-02"],
        "precipitation_sum": [0.0, 1.2],
        "et0_fao_evapotranspiration": [1.5, 0.8],
        "temperature_2m_mean": [15.0, 14.2],
        "temperature_2m_max": [20.0, 19.1],
        "temperature_2m_min": [10.0, 9.3],
    },
}

CACHE_KEY_PATTERN = "omarchive:41.38:2.15:2023:2023"


@pytest.fixture
def mock_redis():
    """Mock Redis client with get/setex/setnx."""
    store = {}

    def fake_get(key):
        return store.get(key)

    def fake_setex(key, ttl, value):
        store[key] = value
        return True

    mock = MagicMock()
    mock.get.side_effect = fake_get
    mock.setex.side_effect = fake_setex
    return mock


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_fetch_uses_cache(monkeypatch, mock_redis):
    """Second call returns cached data without hitting the network."""
    import json
    from app.services import openmeteo_archive as oma

    # Inject mock redis
    oma._get_redis_client = MagicMock(return_value=mock_redis)
    monkeypatch.setattr(oma, "_get_redis_client", lambda: mock_redis)

    http_get_calls = []

    def fake_http_get(url, **kw):
        http_get_calls.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        return resp

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = fake_http_get

        # First call — should hit network
        result1 = oma.fetch_historical_daily(
            lat=41.38, lon=2.15, start_year=2023, end_year=2023,
        )

        assert len(http_get_calls) == 1
        assert result1["latitude"] == 41.38
        # Verify data was cached
        cached = mock_redis.get(CACHE_KEY_PATTERN)
        assert cached is not None
        assert json.loads(cached) == SAMPLE_API_RESPONSE

        # Second call — should use cache, no network
        result2 = oma.fetch_historical_daily(
            lat=41.38, lon=2.15, start_year=2023, end_year=2023,
        )

        assert len(http_get_calls) == 1  # No new network call
        assert result2 == SAMPLE_API_RESPONSE


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_fetch_parses_response(monkeypatch, mock_redis):
    """Returns the same structure as the API response."""
    from app.services import openmeteo_archive as oma

    oma._get_redis_client = MagicMock(return_value=mock_redis)

    def fake_http_get(url, **kw):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        return resp

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = fake_http_get

        result = oma.fetch_historical_daily(
            lat=41.38, lon=2.15, start_year=2023, end_year=2023,
        )

    # Verify the response structure
    assert isinstance(result, dict)
    assert result["latitude"] == SAMPLE_API_RESPONSE["latitude"]
    assert result["longitude"] == SAMPLE_API_RESPONSE["longitude"]
    assert "daily" in result
    assert "daily_units" in result
    assert "time" in result["daily"]
    assert "precipitation_sum" in result["daily"]
    assert "temperature_2m_mean" in result["daily"]
    assert result["daily"]["precipitation_sum"] == [0.0, 1.2]
    assert result["daily"]["temperature_2m_mean"] == [15.0, 14.2]


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_force_refresh_skips_cache(monkeypatch, mock_redis):
    """force_refresh=True skips the cache and fetches from API."""
    from app.services import openmeteo_archive as oma

    # Pre-seed cache
    import json
    mock_redis.setex(CACHE_KEY_PATTERN, 86400, json.dumps(SAMPLE_API_RESPONSE))
    oma._get_redis_client = MagicMock(return_value=mock_redis)

    http_get_calls = []

    def fake_http_get(url, **kw):
        http_get_calls.append(url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        return resp

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = fake_http_get

        oma.fetch_historical_daily(
            lat=41.38, lon=2.15, start_year=2023, end_year=2023,
            force_refresh=True,
        )

    # Network was hit despite cache being present
    assert len(http_get_calls) == 1


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_http_error_falls_back_to_stale_cache(monkeypatch, mock_redis):
    """On HTTP error, stale cache is returned if available."""
    from app.services import openmeteo_archive as oma

    # Pre-seed cache with stale data
    import json
    mock_redis.setex(CACHE_KEY_PATTERN, 86400, json.dumps(SAMPLE_API_RESPONSE))
    oma._get_redis_client = MagicMock(return_value=mock_redis)

    def failing_get(url, **kw):
        raise oma.httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = failing_get

        result = oma.fetch_historical_daily(
            lat=41.38, lon=2.15, start_year=2023, end_year=2023,
        )

    assert result == SAMPLE_API_RESPONSE


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_http_error_raises_without_stale_cache(monkeypatch, mock_redis):
    """On HTTP error with no stale cache, the exception is re-raised."""
    from app.services import openmeteo_archive as oma

    oma._get_redis_client = MagicMock(return_value=mock_redis)

    def failing_get(url, **kw):
        raise oma.httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = failing_get

        with pytest.raises(oma.httpx.HTTPStatusError):
            oma.fetch_historical_daily(
                lat=41.38, lon=2.15, start_year=2023, end_year=2023,
            )


@pytest.mark.skipif(not HAS_REDIS, reason="redis not installed")
def test_default_variables_included(monkeypatch, mock_redis):
    """Default variables list is used when none are specified."""
    from app.services import openmeteo_archive as oma

    oma._get_redis_client = MagicMock(return_value=mock_redis)

    captured_url = [None]

    def capture_get(url, **kw):
        captured_url[0] = url
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=SAMPLE_API_RESPONSE)
        return resp

    with patch.object(oma.httpx, "Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get = capture_get

        oma.fetch_historical_daily(lat=41.38, lon=2.15, start_year=2023, end_year=2023)

    # Verify all default variables are in the URL
    for var in oma.DEFAULT_VARIABLES:
        assert var in captured_url[0], f"Missing variable {var} in URL"
