"""
Tests for the RQ worker entry point (run_dem_pipeline).
Skip-guarded if geolibre-wasm not installed.
"""

import pytest

try:
    import geolibre_wasm as gl
    HAS_GEOLIBRE = True
except ImportError:
    HAS_GEOLIBRE = False

pytestmark = pytest.mark.skipif(
    not HAS_GEOLIBRE, reason="geolibre-wasm not installed"
)


class TestWorker:
    """Test suite for hydrology_worker.run_dem_pipeline."""

    def test_run_dem_pipeline_returns_expected_result(self):
        """run_dem_pipeline produces correct structure for a synthetic parcel."""
        from app.workers.hydrology_worker import run_dem_pipeline

        result = run_dem_pipeline(parcel_id="test-parcel-001", job_id="test-job-1")

        assert result["status"] == "done"
        assert result["parcel_id"] == "test-parcel-001"
        assert result["outputs"] is not None

        expected_keys = {
            "breached.tif", "accum.tif", "streams.tif", "pntr.tif",
            "streams.geojson", "slope.tif", "aspect.tif", "twi.tif",
        }
        assert set(result["outputs"]) == expected_keys

        # Raster outputs must be non-trivial; the vectorized network must exist.
        for key in expected_keys:
            assert result["sizes"][key] > 50, f"{key} output too short"
        assert result["sizes"]["streams.geojson"] > 50

    def test_run_dem_pipeline_logs_no_upload(self):
        """run_dem_pipeline runs without error in Fase 0 (synthetic DEM)."""
        from app.workers.hydrology_worker import run_dem_pipeline

        result = run_dem_pipeline(parcel_id="test-parcel-002", job_id="test-job-2")
        assert result["status"] == "done"
        assert all(v > 0 for v in result["sizes"].values())
