"""The eu-elevation grid is placed from its north edge (row 0 = north)."""
import io

import numpy as np
import pytest
import rasterio
from rasterio.warp import transform_bounds

from app.services.dem_client import DEMGrid
from app.workers.hydrology_worker import _reproject_to_utm


def _grid(north_lat=None) -> DEMGrid:
    rows = [[100.0 - 10.0 * r] * 10 for r in range(10)]  # row 0 = 100 m, row 9 = 10 m
    return DEMGrid(
        elevations=rows, origin_lon=-1.0, origin_lat=42.0, pixel_size_deg=0.001,
        cols=10, rows=10, source={}, north_lat=north_lat,
    )


def _bounds_and_rows(tif: bytes):
    with rasterio.open(io.BytesIO(tif)) as ds:
        bounds = transform_bounds(ds.crs, "EPSG:4258", *ds.bounds)
        band = ds.read(1, masked=True)
    valid = [row for row in band if row.count() > 0]
    return bounds, valid


def test_reprojected_dem_stays_inside_requested_bbox():
    (_, south, _, north), _ = _bounds_and_rows(_reproject_to_utm(_grid()))
    assert south >= 41.999
    assert north <= 42.011


def test_reprojected_dem_keeps_high_row_north():
    _, valid = _bounds_and_rows(_reproject_to_utm(_grid()))
    assert valid[0].mean() > valid[-1].mean()


def test_declared_north_lat_wins():
    (_, _, _, north), _ = _bounds_and_rows(_reproject_to_utm(_grid(north_lat=42.0102)))
    assert north == pytest.approx(42.0102, abs=0.0002)
