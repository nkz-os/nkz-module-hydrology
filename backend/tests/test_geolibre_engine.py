"""
Tests for GeoLibreEngine. Skip-guarded if geolibre-wasm not installed.
Uses synthetic 50x50 DEM in EPSG:25830.
"""

import json
import tempfile

import numpy as np
import pytest

try:
    import geolibre_wasm as gl
    HAS_GEOLIBRE = True
except ImportError:
    HAS_GEOLIBRE = False

pytestmark = pytest.mark.skipif(
    not HAS_GEOLIBRE, reason="geolibre-wasm not installed"
)


@pytest.fixture(scope="module")
def synthetic_dem() -> bytes:
    """Create 50x50 synthetic DEM with a V-shaped valley."""
    import rasterio
    from rasterio.transform import from_origin

    size = 50
    dem = np.fromfunction(
        lambda i, j: 100 + abs(j - size // 2) * 0.5,
        (size, size), dtype=np.float32
    )
    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        with rasterio.open(
            tmp.name, "w", driver="GTiff",
            height=size, width=size, count=1, dtype="float32",
            crs="EPSG:25830",
            transform=from_origin(600000, 4700000, 1.0, 1.0),
        ) as dst:
            dst.write(dem, 1)
        with open(tmp.name, "rb") as f:
            return f.read()


class TestGeoLibreEngine:
    """Test suite for GeoLibreEngine."""

    def test_fill_depressions(self, synthetic_dem):
        """Fill depressions produces a valid GeoTIFF."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        assert len(filled) > 100
        # TIFF little-endian magic
        assert filled[:2] == b"\x49\x49"

    def test_breach_depressions(self, synthetic_dem):
        """Breach depressions produces a valid GeoTIFF."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        breached = eng.breach_depressions(filled)
        assert len(breached) > 100
        assert breached[:2] == b"\x49\x49"

    def test_flow_accumulation(self, synthetic_dem):
        """Flow accumulation via workaround produces valid output."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        accum = eng.flow_accumulation(filled)
        assert len(accum) > 100
        assert accum[:2] == b"\x49\x49"

    def test_extract_streams(self, synthetic_dem):
        """Extract streams works from flow accumulation."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        accum = eng.flow_accumulation(filled)
        streams = eng.extract_streams(accum, threshold=100)
        assert len(streams) > 100

    def test_slope_aspect(self, synthetic_dem):
        """Slope and aspect produce valid outputs."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        slope = eng.slope(synthetic_dem)
        aspect = eng.aspect(synthetic_dem)
        assert len(slope) > 100
        assert len(aspect) > 100

    def test_wetness_index(self, synthetic_dem):
        """TWI computed from flow accumulation + slope."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        filled = eng.fill_depressions(synthetic_dem)
        accum = eng.flow_accumulation(filled)
        slope = eng.slope(filled)
        twi = eng.wetness_index(accum, slope)
        assert len(twi) > 100
        assert twi[:2] == b"\x49\x49"

    def test_full_pipeline(self, synthetic_dem):
        """End-to-end DEM pipeline produces all expected outputs."""
        from app.services.geolibre_engine import GeoLibreEngine
        eng = GeoLibreEngine()
        result = eng.run_dem_pipeline(synthetic_dem)
        expected_keys = {
            "filled.tif", "accum.tif", "streams.tif",
            "slope.tif", "aspect.tif", "twi.tif",
        }
        assert set(result.keys()) == expected_keys
        for key, data in result.items():
            assert len(data) > 100, f"{key} is too short"
            assert data[:2] == b"\x49\x49", f"{key} is not a valid TIFF"
