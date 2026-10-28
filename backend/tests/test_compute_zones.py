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


def _twi_tif_nodata(values, nodata=-9999.0):
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=values.shape[0],
        width=values.shape[1], count=1, dtype="float32", crs="EPSG:25830",
        transform=rasterio.transform.from_origin(600000.0, 4700000.0, 10.0, 10.0),
        nodata=nodata,
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


def test_compute_zones_excludes_nodata_fill():
    """-9999.0 UTM fill (declared nodata) must not leak into quintiles."""
    grid = np.full((10, 10), -9999.0, dtype="float32")
    grid[2:8, 2:8] = np.arange(36, dtype="float32").reshape(6, 6)
    zones = _compute_zones({"twi.tif": _twi_tif_nodata(grid)})
    assert zones
    for z in zones:
        assert "-9999" not in z["twiRange"], z["twiRange"]
        assert z["twiMean"] >= 0.0


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


def test_compute_zones_geometry_stays_under_the_payload_budget():
    # A speckled high-resolution TWI (LiDAR-like 0.5 m cells) polygonizes into
    # thousands of rings; each zone must still fit one broker request.
    import json

    from app.workers.hydrology_worker import MAX_ZONE_GEOMETRY_BYTES

    rng = np.random.default_rng(7)
    grid = rng.normal(8.0, 2.0, size=(400, 400))
    zones = _compute_zones({"twi.tif": _twi_tif(grid, pixel=0.5)})
    assert len(zones) == 5
    for z in zones:
        assert z["geometry"].get("type") in ("Polygon", "MultiPolygon")
        assert len(json.dumps(z["geometry"])) <= MAX_ZONE_GEOMETRY_BYTES
        x, y = _first_xy(z["geometry"]["coordinates"])
        assert round(x, 6) == x and round(y, 6) == y


def test_compute_zones_geometry_is_valid_for_the_broker():
    # The broker's geo index refuses self-crossing rings ("Loop is not valid"):
    # simplification and coordinate rounding must still leave valid polygons.
    from shapely.geometry import shape
    from shapely.validation import explain_validity

    rng = np.random.default_rng(11)
    grid = rng.normal(8.0, 2.0, size=(400, 400))
    for z in _compute_zones({"twi.tif": _twi_tif(grid, pixel=0.5)}):
        geom = shape(z["geometry"])
        assert geom.is_valid, explain_validity(geom)
        assert geom.geom_type in ("Polygon", "MultiPolygon")
        assert geom.area > 0


def test_broker_geometry_repairs_the_ring_the_broker_refused():
    # Ring copied from the broker's "Loop is not valid ... Edges 0 and 4 cross" error.
    from shapely.geometry import Polygon, shape

    from app.workers.hydrology_worker import _broker_geometry

    bad = Polygon([(-2.091478, 42.63319), (-2.091472, 42.633204), (-2.091472, 42.63319),
                   (-2.091447, 42.633195), (-2.091399, 42.633185), (-2.09149, 42.633191)])
    assert not bad.is_valid
    out = _broker_geometry(bad)
    geom = shape(out)
    assert geom.is_valid and geom.area > 0
    x, y = _first_xy(out["coordinates"])
    assert round(x, 6) == x and round(y, 6) == y


def test_broker_geometry_drops_collapsed_parts():
    from shapely.geometry import Polygon

    from app.workers.hydrology_worker import _broker_geometry

    sliver = Polygon([(0, 0), (1e-8, 0), (1e-8, 1e-8), (0, 1e-8)])
    assert _broker_geometry(sliver) == {}
