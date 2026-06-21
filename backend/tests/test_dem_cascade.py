"""Tests for DEM cascade fetcher."""

from unittest.mock import AsyncMock
import pytest


@pytest.mark.asyncio
async def test_centroid_key_is_deterministic():
    from app.services.dem_cascade import _centroid_key
    assert _centroid_key(42.06, -1.60) == _centroid_key(42.06, -1.60)
    assert len(_centroid_key(42.06, -1.60)) == 16


@pytest.mark.asyncio
async def test_fetch_dem_raises_on_no_source(monkeypatch):
    """All providers return None → RuntimeError."""
    from app.services import dem_cascade as dc
    monkeypatch.setattr(dc, "_try_lidar", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_try_pnoa", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_try_ign", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_try_copernicus", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_minio_get", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError):
        await dc.fetch_dem(42.06, -1.60, "p-1")


@pytest.mark.asyncio
async def test_cascade_uses_first_available(monkeypatch):
    from app.services import dem_cascade as dc
    dummy = b"geotiff-data"
    monkeypatch.setattr(dc, "_try_lidar", AsyncMock(return_value=dummy))
    monkeypatch.setattr(dc, "_try_pnoa", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_try_ign", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_try_copernicus", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_minio_get", AsyncMock(return_value=None))
    monkeypatch.setattr(dc, "_minio_put", AsyncMock())

    result = await dc.fetch_dem(42.06, -1.60, "p-1")
    assert result == dummy


@pytest.mark.asyncio
async def test_cache_hit_skips_providers(monkeypatch):
    from app.services import dem_cascade as dc
    cached = b"cached-dem"
    monkeypatch.setattr(dc, "_minio_get", AsyncMock(return_value=cached))

    # If any provider is called, fail
    async def fail(*a):
        raise AssertionError("provider called despite cache hit")
    monkeypatch.setattr(dc, "_try_lidar", fail)
    monkeypatch.setattr(dc, "_try_pnoa", fail)
    monkeypatch.setattr(dc, "_try_ign", fail)
    monkeypatch.setattr(dc, "_try_copernicus", fail)

    result = await dc.fetch_dem(42.06, -1.60, "p-1")
    assert result == cached
