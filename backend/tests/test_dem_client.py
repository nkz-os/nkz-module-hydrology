"""Tests for DEMClient (eu-elevation service-to-service, no auth)."""
from unittest.mock import patch, MagicMock

import pytest

from app.services.dem_client import DEMClient, DEMGrid, DEMUnavailable, resolution_for_area_ha


def _grid_json(cols=4, rows=4, elev=440.0):
    return {
        "elevations": [[elev] * cols for _ in range(rows)],
        "origin_lon": -1.645, "origin_lat": 42.822,
        "pixel_size_deg": 0.0002, "cols": cols, "rows": rows,
        "source": {"id": "builtin:ES", "name": "Espana", "resolution_m": 25},
    }


def test_fetch_dem_returns_grid():
    client = DEMClient(base_url="http://elevation-api-service:80")
    fake = MagicMock(status_code=200, json=MagicMock(return_value=_grid_json()))
    with patch("app.services.dem_client.httpx.get", return_value=fake):
        grid = client.fetch_dem((-1.645, 42.812, -1.635, 42.822), resolution_m=25.0)
    assert isinstance(grid, DEMGrid)
    assert grid.cols == 4 and grid.rows == 4
    assert grid.origin_lon == -1.645
    assert grid.elevations[0][0] == 440.0


def test_fetch_dem_sends_tenant_header():
    client = DEMClient(base_url="http://elevation-api-service:80")
    fake = MagicMock(status_code=200, json=MagicMock(return_value=_grid_json()))
    captured = {}

    def grab(url, params=None, headers=None, timeout=None):
        captured.update(headers or {})
        return fake

    with patch("app.services.dem_client.httpx.get", side_effect=grab):
        client.fetch_dem((-1.645, 42.812, -1.635, 42.822), resolution_m=25.0, tenant_id="t1")
    assert captured.get("X-Tenant-ID") == "t1"


def test_fetch_dem_404_raises_dem_unavailable():
    client = DEMClient(base_url="http://elevation-api-service:80")
    fake = MagicMock(status_code=404, text="no coverage")
    with patch("app.services.dem_client.httpx.get", return_value=fake):
        with pytest.raises(DEMUnavailable):
            client.fetch_dem((-1.645, 42.812, -1.635, 42.822), resolution_m=25.0)


def test_resolution_by_area_small_parcel_5m():
    assert resolution_for_area_ha(3.0) == 5.0   # < 10 ha -> 5m


def test_resolution_by_area_large_parcel_25m():
    assert resolution_for_area_ha(25.0) == 25.0  # >= 10 ha -> 25m
