"""
Tests for GeoLibreEngine. Skip-guarded if geolibre-wasm not installed.
Uses a synthetic DEM (valley + downslope) in EPSG:25830.

Covers the geolibre-wasm 0.4.4 workaround: flow accumulation via the composite
workflow + D8 pointer derived in numpy + stream vectorization.
"""

import json
import tempfile

import numpy as np
import pytest

try:
    import geolibre_wasm as gl  # noqa: F401
    HAS_GEOLIBRE = True
except ImportError:
    HAS_GEOLIBRE = False

pytestmark = pytest.mark.skipif(
    not HAS_GEOLIBRE, reason="geolibre-wasm not installed"
)

TIFF_MAGIC = b"\x49\x49"  # little-endian GeoTIFF


@pytest.fixture(scope="module")
def synthetic_dem() -> bytes:
    """Create a synthetic DEM with a V-shaped valley AND a downslope along i,
    so flow concentrates and produces a real stream network."""
    import rasterio
    from rasterio.transform import from_origin

    # i-slope (0.5/cell) must dominate the noise (0.25) so drainage stays
    # connected; a too-gentle slope leaves the breached DEM with no through-flow
    # and accumulation collapses (terrain artefact, not an engine bug).
    size = 120
    dem = np.fromfunction(
        lambda i, j: 100 + abs(j - size // 2) * 0.7 + i * 0.5,
        (size, size), dtype=np.float32,
    )
    np.random.seed(5)
    dem += np.random.rand(size, size).astype(np.float32) * 0.25
    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        with rasterio.open(
            tmp.name, "w", driver="GTiff",
            height=size, width=size, count=1, dtype="float32",
            crs="EPSG:25830",
            transform=from_origin(600000, 4700000, 2.0, 2.0), nodata=-9999.0,
        ) as dst:
            dst.write(dem, 1)
        with open(tmp.name, "rb") as f:
            return f.read()


# ── pure numpy pointer (no geolibre needed) ───────────────────────────
def test_d8_pointer_esri_pure():
    """ESRI codes are valid, borders/sinks are 0, a clear slope drains one way."""
    from app.services.geolibre_engine import d8_pointer_esri

    # Plane tilted so every interior cell drains east (code 1).
    z = np.fromfunction(lambda i, j: 100 - j, (10, 10), dtype="float64")
    code = d8_pointer_esri(z)
    valid_codes = {0, 1, 2, 4, 8, 16, 32, 64, 128}
    assert set(np.unique(code)).issubset(valid_codes)
    # Interior cells (not last column) drain east.
    assert np.all(code[1:-1, 1:-2] == 1)
    # Cells with no lower neighbour available stay 0 (e.g. global low edge).
    assert code[0, 0] in valid_codes


def test_d8_pointer_esri_nodata():
    from app.services.geolibre_engine import d8_pointer_esri
    z = np.full((6, 6), -9999.0)
    z[2:4, 2:4] = [[10, 9], [8, 7]]
    code = d8_pointer_esri(z, nodata=-9999.0)
    assert np.all(code[z == -9999.0] == 0)


# ── geolibre-backed tools ─────────────────────────────────────────────
class TestGeoLibreEngine:
    def test_fill_depressions(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        filled = GeoLibreEngine().fill_depressions(synthetic_dem)
        assert len(filled) > 100 and filled[:2] == TIFF_MAGIC

    def test_breach_depressions(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        breached = GeoLibreEngine().breach_depressions(synthetic_dem)
        assert len(breached) > 100 and breached[:2] == TIFF_MAGIC

    def test_flow_accumulation(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        accum = GeoLibreEngine().flow_accumulation(synthetic_dem)
        assert len(accum) > 100 and accum[:2] == TIFF_MAGIC

    def test_extract_streams(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        accum = eng.flow_accumulation(synthetic_dem)
        streams = eng.extract_streams(accum, threshold=80)
        assert len(streams) > 100 and streams[:2] == TIFF_MAGIC

    def test_d8_pointer_geotiff(self, synthetic_dem):
        """Pointer is produced as a valid GeoTIFF from a breached DEM."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        breached = eng.breach_depressions(synthetic_dem)
        pntr = eng.d8_pointer(breached)
        assert len(pntr) > 100 and pntr[:2] == TIFF_MAGIC

    def test_streams_to_vector(self, synthetic_dem):
        """The key restored capability: vectorized drainage network."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        breached = eng.breach_depressions(synthetic_dem)
        accum = eng.flow_accumulation(synthetic_dem)
        streams = eng.extract_streams(accum, threshold=80)
        pntr = eng.d8_pointer(breached)
        geojson = eng.streams_to_vector(streams, pntr)
        fc = json.loads(geojson.decode("utf-8"))
        assert fc.get("type") == "FeatureCollection"
        assert len(fc["features"]) > 0

    def test_slope_aspect(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        assert len(eng.slope(synthetic_dem)) > 100
        assert len(eng.aspect(synthetic_dem)) > 100

    def test_wetness_index(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        accum = eng.flow_accumulation(synthetic_dem)
        slope = eng.slope(synthetic_dem)
        twi = eng.wetness_index(accum, slope)
        assert len(twi) > 100 and twi[:2] == TIFF_MAGIC

    def test_full_pipeline(self, synthetic_dem):
        """End-to-end DEM pipeline, including stream vectorization."""
        from app.services.geolibre_engine import GeoLibreEngine
        result = GeoLibreEngine().run_dem_pipeline(synthetic_dem)
        expected = {
            "breached.tif", "accum.tif", "streams.tif", "pntr.tif",
            "streams.geojson", "slope.tif", "aspect.tif", "twi.tif",
        }
        assert set(result.keys()) == expected
        for key, data in result.items():
            assert len(data) > 50, f"{key} too short"
            if key.endswith(".tif"):
                assert data[:2] == TIFF_MAGIC, f"{key} not a TIFF"
        # The drainage network must be valid GeoJSON with features.
        fc = json.loads(result["streams.geojson"].decode("utf-8"))
        assert fc["type"] == "FeatureCollection" and len(fc["features"]) > 0



# ── Characterization of the geolibre-wasm 0.4.4 crash family ──────────
# See internal-docs-local/issues/geolibre-d8-trap.md. `basins`/`subbasins`
# trap with the same shared WASM error as the D8 tools. This xfails now and
# will xpass once upstream fixes it; strict=True then fails the suite so we
# remember to drop the numpy/watershed workarounds. `watershed` itself is NOT
# broken (it just needs a vector pour-point file), so no xfail for it.
@pytest.mark.xfail(strict=True,
                   reason="geolibre-wasm 0.4.4: basins traps (wasm fn 7349)")
def test_basins_traps(synthetic_dem):
    from app.services.geolibre_engine import GeoLibreEngine
    eng = GeoLibreEngine()
    breached = eng.breach_depressions(synthetic_dem)
    r = gl.run_tool("basins", args=["--input=/work/b.tif", "--output=/work/o.tif"],
                    input={"b.tif": breached})
    assert r.exit_code == 0  # unreachable in 0.4.4 — the tool traps first


class TestCatchment:
    """Catchment from point (numpy BFS, replaces broken basins)."""

    def test_catchment_from_point(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        pntr = eng.d8_pointer(filled)
        # Pour point at valley center
        catch = eng.catchment_from_point(pntr, pour_col=25, pour_row=25)
        assert len(catch) > 100
        assert catch[:2] == b"\x49\x49"

    def test_catchment_out_of_bounds(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        pntr = eng.d8_pointer(filled)
        catch = eng.catchment_from_point(pntr, pour_col=-1, pour_row=-1)
        assert len(catch) > 100

    def test_denylist_blocks_broken_tools(self, synthetic_dem):
        from app.services.geolibre_engine import GeoLibreEngine, GeoLibreError, _BROKEN_TOOLS
        eng = GeoLibreEngine()
        for tool_id in _BROKEN_TOOLS:
            with pytest.raises(GeoLibreError) as exc:
                eng._run(tool_id, [], {})
            assert "BROKEN" in str(exc.value)
