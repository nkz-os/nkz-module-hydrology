"""_compute_zones must emit real WGS84 polygon geometry (Phase 1.1).

Regression: previously zones were published with geometry={} and areaHa=0 —
the zonal map layer could not render anything. extract_zonal_stats pairs
zones by the ``twiRange`` string, so that format MUST be preserved.
"""
import io

import numpy as np
import rasterio

from app.workers.hydrology_worker import _compute_zones


def _twi_tif(values, crs="EPSG:25830", origin=(600000.0, 4700000.0), pixel=10.0):
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=values.shape[0],
        width=values.shape[1], count=1, dtype="float32", crs=crs,
        transform=rasterio.transform.from_origin(origin[0], origin[1], pixel, pixel),
    ) as dst:
        dst.write(values.astype("float32"), 1)
    return buf.getvalue()


def _first_xy(coords):
    if isinstance(coords[0], (int, float)):
        return coords[0], coords[1]
    return _first_xy(coords[0])


def test_compute_zones_emits_wgs84_polygon_geometry():
    # Horizontal bands of increasing TWI -> 5 contiguous quintile zones,
    # each a rectangle polygon (not thousands of pixel rings).
    rows = np.arange(50, dtype="float32").reshape(50, 1)
    grid = np.repeat(rows, 10, axis=1)  # values 0..49 across rows
    twi = _twi_tif(grid)

    zones = _compute_zones({"twi.tif": twi})

    assert len(zones) == 5
    for z in zones:
        geom = z["geometry"]
        assert geom.get("type") in ("Polygon", "MultiPolygon"), z["zone_id"]
        # Must be reprojected to WGS84 lon/lat, NOT raw UTM metres (600000...).
        x, y = _first_xy(geom["coordinates"])
        assert -180 < x < 180, f"lon not WGS84: {x}"
        assert -90 < y < 90, f"lat not WGS84: {y}"
        # twiRange string preserved for extract_zonal_stats compatibility.
        assert "-" in z["twiRange"]
        assert z["pixelCount"] > 0
        assert z["areaHa"] > 0


def test_compute_zones_empty_when_all_invalid():
    twi = _twi_tif(np.full((10, 10), np.nan, dtype="float32"))
    assert _compute_zones({"twi.tif": twi}) == []


def test_compute_zones_twi_range_round_trips_through_zonal_stats():
    """extract_zonal_stats must be able to parse every emitted twiRange."""
    from app.services.zonal_stats import _parse_twi_range

    rows = np.arange(50, dtype="float32").reshape(50, 1)
    grid = np.repeat(rows, 10, axis=1)
    slope = _twi_tif(grid * 0.1)

    zones = _compute_zones({"twi.tif": _twi_tif(grid)})
    for z in zones:
        lo, hi = _parse_twi_range(z["twiRange"])  # raises on bad format
        assert lo < hi
    _ = slope  # slope raster unused here; parser contract is the point
