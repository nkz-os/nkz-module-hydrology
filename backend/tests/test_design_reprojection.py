"""Tests for UTM -> WGS84 reprojection of design geometry and real
check-dam placement at slope inflections.

All design endpoints compute geometry on ETRS89 UTM rasters (EPSG:258xx)
but MUST return WGS84 lon/lat: Cesium `fromDegreesArray`, GPX/KML export
and GIS-routing ingest all assume EPSG:4326.
"""
import io
import json
import math
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin


UTM_CRS = "EPSG:25830"
_TRANSFORM = from_origin(500000, 4750000, 5, 5)
_N = 40


def _synthetic_utm_dem() -> bytes:
    """40x40 ETRS89/UTM-30N GeoTIFF: tilted plane with a central valley."""
    j = np.arange(_N)
    i = np.arange(_N)
    J, I = np.meshgrid(j, i)
    z = 200 + (_N - I) * 0.8 + np.abs(J - _N / 2) * 1.2
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=_N, width=_N, count=1,
        dtype="float32", crs=UTM_CRS, transform=_TRANSFORM,
    ) as dst:
        dst.write(z.astype(np.float32), 1)
    return buf.getvalue()


# ── Helper reprojection ────────────────────────────────────────────────

def _in_spain(lon, lat):
    return -10.0 <= lon <= 0.0 and 35.0 <= lat <= 45.0


class TestToWgs84Helper:
    def test_single_point_xy_reprojected_to_spain(self):
        from app.api.designs import _to_wgs84
        lon, lat = _to_wgs84([500100.0, 4749900.0], UTM_CRS)
        assert _in_spain(lon, lat), f"({lon},{lat}) not in Spain bbox"

    def test_point_preserves_z(self):
        from app.api.designs import _to_wgs84
        out = _to_wgs84([500100.0, 4749900.0, 213.5], UTM_CRS)
        assert len(out) == 3
        assert out[2] == 213.5
        assert _in_spain(out[0], out[1])

    def test_list_of_coords_all_in_spain(self):
        from app.api.designs import _to_wgs84
        coords = [[500000 + c * 5, 4750000 - r * 5]
                  for c in range(0, 40, 5) for r in range(0, 40, 5)]
        out = _to_wgs84(coords, UTM_CRS)
        assert len(out) == len(coords)
        for lon, lat in out:
            assert _in_spain(lon, lat), f"({lon},{lat}) not in Spain bbox"


# ── Pond scoring reprojects the client center (WGS84 -> raster CRS) ─────

class TestScorePondReprojectsCenter:
    def test_wgs84_center_inside_raster_scores_ok(self):
        """Frontend sends center as WGS84 [lon, lat]; score_pond must
        reproject it to the raster CRS before the ~transform math, or every
        real pick falls out of bounds."""
        from pyproj import Transformer

        from app.api import designs

        # A point well inside the 40x40 EPSG:25830 raster, in WGS84.
        fwd = Transformer.from_crs(UTM_CRS, "EPSG:4326", always_xy=True)
        lon, lat = fwd.transform(500100.0, 4749900.0)

        def _dem_only(parcel_id, tenant_id, raster_name):
            return _synthetic_utm_dem() if raster_name == "breached.tif" else None

        with patch.object(designs, "download_raster", side_effect=_dem_only):
            res = designs.score_pond(
                req=designs.PondScoreRequest(parcel_id="p1", center=[lon, lat]),
                auth=SimpleNamespace(tenant_id="t1", user_id="u1"),
            )
        assert res["status"] == "ok", f"expected ok, got {res}"


# ── Check-dam placement at inflections ─────────────────────────────────

def _stream_crossing_valley() -> bytes:
    """GeoJSON stream (UTM) running E-W across the valley -> V profile."""
    y = 4750000 - (10 + 0.5) * 5
    coords = [[500000 + (c + 0.5) * 5, y] for c in range(2, 38)]
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {},
        }],
    }
    return json.dumps(fc).encode()


def _fake_download(parcel_id, tenant_id, raster_name):
    if raster_name == "streams.geojson":
        return _stream_crossing_valley()
    if raster_name == "breached.tif":
        return _synthetic_utm_dem()
    return None


class TestCheckDamPlacement:
    def test_dams_are_wgs84_and_distinct(self):
        from app.api import designs
        with patch.object(designs, "download_raster", side_effect=_fake_download):
            res = designs.suggest_check_dams(
                req=designs.CheckDamSuggestRequest(parcel_id="p1"),
                auth=SimpleNamespace(tenant_id="t1", user_id="u1"),
            )
        assert res["status"] == "ok"
        dams = res["dams"]
        assert len(dams) >= 2, "V-crossing stream should yield >=2 inflections"
        # WGS84 output
        for d in dams:
            lon, lat = d["coordinates"]
            assert _in_spain(lon, lat), f"dam not in Spain bbox: {d['coordinates']}"
        # Distinct inflections -> distinct coordinates (not all coords[0])
        uniq = {tuple(d["coordinates"]) for d in dams}
        assert len(uniq) == len(dams), "dams collapsed to a single point"
