"""Tests for UTM zone derivation + grid reprojection (CRS trap #1 defense)."""
import io

import numpy as np
import pytest
import rasterio

from app.services.utm import (
    utm_zone_from_centroid,
    utm_epsg_from_centroid,
    reproject_grid_to_utm,
)


def test_utm_zone_pamplona_is_30():
    # Pamplona (-1.64, 42.82) -> UTM zone 30
    assert utm_zone_from_centroid(-1.6432, 42.8167) == 30


def test_utm_zone_barcelona_is_31():
    # Barcelona (2.17, 41.39) -> UTM zone 31
    assert utm_zone_from_centroid(2.1734, 41.3851) == 31


def test_utm_epsg_is_etrs89_northern_hemisphere():
    # Spain is always northern hemisphere -> EPSG:258NN
    assert utm_epsg_from_centroid(-1.6432, 42.8167) == "EPSG:25830"
    assert utm_epsg_from_centroid(2.1734, 41.3851) == "EPSG:25831"


def test_reproject_grid_to_utm_yields_metric_cellsize():
    """A grid in EPSG:4258 (degrees) reprojected to UTM has metric cellsize."""
    cols, rows = 10, 10
    elev = np.full((rows, cols), 440.0, dtype="float32")
    pixel_deg = 0.0002  # ~22 m at this latitude
    origin_lon, origin_lat = -1.645, 42.812
    geotiff = _build_geotiff_bytes(elev, origin_lon, origin_lat, pixel_deg, crs="EPSG:4258")

    utm_bytes = reproject_grid_to_utm(
        geotiff, centroid_lon=origin_lon, centroid_lat=origin_lat
    )

    with rasterio.open(io.BytesIO(utm_bytes)) as ds:
        # cellsize in metres (~ the reprojected resolution), NOT degrees
        xres, yres = abs(ds.transform.a), abs(ds.transform.e)
        assert 5.0 < xres < 40.0, f"xres={xres} not metric"
        assert 5.0 < yres < 40.0
        assert str(ds.crs).startswith("EPSG:258"), ds.crs
        # Elevation preserved on valid cells (mask nodata at reprojected edges).
        band = ds.read(1, masked=True)
        valid = band.compressed()
        assert valid.size > 0
        assert abs(float(valid.mean()) - 440.0) < 1.0, f"mean={valid.mean()}"


def _build_geotiff_bytes(arr, origin_lon, origin_lat, pixel_deg, crs="EPSG:4258"):
    buf = io.BytesIO()
    transform = rasterio.transform.from_origin(origin_lon, origin_lat, pixel_deg, pixel_deg)
    with rasterio.open(
        buf, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
        count=1, dtype=str(arr.dtype), crs=crs, transform=transform,
    ) as dst:
        dst.write(arr, 1)
    return buf.getvalue()
