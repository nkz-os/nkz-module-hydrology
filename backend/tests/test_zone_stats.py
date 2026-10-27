"""Tests for per-zone TWI statistics (synthetic 20x20 raster, EPSG:25830)."""
import numpy as np
import rasterio
from rasterio.warp import transform_geom

from app.services.zone_stats import parcel_p80, zone_stats

CRS = "EPSG:25830"
X0, Y0, PX = 600000.0, 4700000.0, 10.0
TRANSFORM = rasterio.transform.from_origin(X0, Y0, PX, PX)


def _poly_wgs84(col0, col1, row0, row1):
    """Pixel-index rectangle -> EPSG:4326 Polygon (inset by 1 m)."""
    xa, xb = X0 + col0 * PX + 1, X0 + col1 * PX - 1
    ya, yb = Y0 - row1 * PX + 1, Y0 - row0 * PX - 1
    utm = {"type": "Polygon", "coordinates": [[[xa, ya], [xb, ya], [xb, yb], [xa, yb], [xa, ya]]]}
    return transform_geom(CRS, "EPSG:4326", utm)


def _rasters():
    twi = np.full((20, 20), 5.0, dtype="float32")
    twi[:10, :] = 20.0  # north half high
    slope = np.full((20, 20), 3.0, dtype="float32")
    accum = np.arange(400, dtype="float32").reshape(20, 20)
    return twi, slope, accum


def test_north_wet_south_dry_zone_specific():
    twi, slope, accum = _rasters()
    zones = [
        {"zoneId": "n", "zoneVersion": "v1", "geometry": _poly_wgs84(0, 20, 0, 10)},
        {"zoneId": "s", "zoneVersion": None, "geometry": _poly_wgs84(0, 20, 10, 20)},
    ]
    p80 = parcel_p80(twi)
    out = zone_stats(twi, slope, accum, TRANSFORM, CRS, zones, p80)
    n, s = out
    assert n["zoneId"] == "n" and n["zoneVersion"] == "v1"
    assert n["fidelity"] == s["fidelity"] == "zone_specific"
    assert n["wetFraction"] > 0.99 and s["wetFraction"] < 0.01
    assert n["twiMean"] == 20.0 and s["twiMean"] == 5.0
    assert n["slopeMean"] == 3.0
    assert n["flowAccumMax"] < s["flowAccumMax"]


def test_small_zone_inherits_parcel_values():
    twi, slope, accum = _rasters()
    zones = [{"zoneId": "tiny", "zoneVersion": None, "geometry": _poly_wgs84(0, 5, 0, 1)}]
    (z,) = zone_stats(twi, slope, accum, TRANSFORM, CRS, zones, parcel_p80(twi))
    assert z["fidelity"] == "parcel_inherited"
    assert z["twiMean"] == float(np.mean(twi))


def test_nan_pixels_excluded():
    twi, slope, accum = _rasters()
    twi[:10, :] = np.nan
    zones = [{"zoneId": "n", "zoneVersion": None, "geometry": _poly_wgs84(0, 20, 0, 10)}]
    (z,) = zone_stats(twi, slope, accum, TRANSFORM, CRS, zones, 5.0)
    assert z["fidelity"] == "parcel_inherited"  # no valid pixels in the zone
