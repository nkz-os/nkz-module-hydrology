"""
Tests for tile_service.py — PMTiles generation & flow line retrieval.

Uses mocking for both geolibre-wasm and boto3 S3 to avoid external deps.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────

MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.minio_endpoint = "http://minio:9000"
MOCK_SETTINGS.minio_access_key = "minioadmin"
MOCK_SETTINGS.minio_secret_key = "minioadmin"
MOCK_SETTINGS.minio_bucket = "nkz-hydrology"
MOCK_SETTINGS.minio_region = "us-east-1"
MOCK_SETTINGS.minio_public_url = "https://minio.example.com"


@pytest.fixture
def patch_settings():
    """Override settings that touch external services.

    Patches the module-level reference in tile_service since it uses
    ``from app.config import get_settings`` at import time.
    """
    with patch("app.services.tile_service.get_settings", return_value=MOCK_SETTINGS):
        yield


@pytest.fixture(scope="module")
def client():
    """Test client with real config (needs REDIS_URL set)."""
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── generate_pmtiles ──────────────────────────────────────────────────

class TestGeneratePMTiles:
    """Tests for the core generate_pmtiles function."""

    @patch("app.services.tile_service.gl.run_tool")
    @patch("app.services.tile_service._s3_client")
    def test_generate_and_upload(self, mock_s3_factory, mock_run_tool, patch_settings):
        """Success case: tool runs, pmtiles uploaded, public URL returned."""
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3

        mock_run_tool.return_value.exit_code = 0
        mock_run_tool.return_value.files = {"twi.pmtiles": b"fake-pmtiles-binary"}
        mock_run_tool.return_value.stdout = b""

        from app.services.tile_service import generate_pmtiles

        url = generate_pmtiles(
            "parcel-123", b"fake-twi-raster",
            raster_name="twi", min_zoom=10, max_zoom=18, colormap="viridis",
        )

        # Verify tool call
        mock_run_tool.assert_called_once_with(
            "write_pmtiles",
            args=[
                "--input=/work/twi.tif",
                "--output=/work/twi.pmtiles",
                "--min_zoom=10",
                "--max_zoom=18",
                "--colormap=viridis",
            ],
            input={"twi.tif": b"fake-twi-raster"},
        )

        # Verify S3 upload
        mock_s3.put_object.assert_called_once_with(
            Bucket="nkz-hydrology",
            Key="pmtiles/parcel-123/twi.pmtiles",
            Body=b"fake-pmtiles-binary",
            ContentType="application/vnd.pmtiles",
        )

        # Verify returned URL
        assert url == (
            "https://minio.example.com/nkz-hydrology/"
            "pmtiles/parcel-123/twi.pmtiles"
        )

    @patch("app.services.tile_service.gl.run_tool")
    @patch("app.services.tile_service._s3_client")
    def test_tool_failure(self, mock_s3_factory, mock_run_tool, patch_settings):
        """When the geolibre tool fails, RuntimeError is raised."""
        mock_run_tool.return_value.exit_code = 1
        mock_run_tool.return_value.stdout = b"some error"

        from app.services.tile_service import generate_pmtiles

        with pytest.raises(RuntimeError, match="write_pmtiles failed"):
            generate_pmtiles("parcel-123", b"raster")

    @patch("app.services.tile_service.gl.run_tool")
    @patch("app.services.tile_service._s3_client")
    def test_no_output_file(self, mock_s3_factory, mock_run_tool, patch_settings):
        """When the tool produces no output, RuntimeError is raised."""
        mock_run_tool.return_value.exit_code = 0
        mock_run_tool.return_value.files = {}

        from app.services.tile_service import generate_pmtiles

        with pytest.raises(RuntimeError, match="produced no output"):
            generate_pmtiles("parcel-123", b"raster")


# ── Convenience wrappers ──────────────────────────────────────────────

class TestTWIandRiskWrappers:
    """generate_twi_pmtiles and generate_risk_pmtiles delegate correctly."""

    @patch("app.services.tile_service.generate_pmtiles")
    def test_twi_pmtiles(self, mock_generate):
        from app.services.tile_service import generate_twi_pmtiles
        mock_generate.return_value = "http://pmtiles/twi"
        url = generate_twi_pmtiles("p1", b"data")
        mock_generate.assert_called_once_with(
            "p1", b"data",
            raster_name="twi", min_zoom=10, max_zoom=18, colormap="viridis",
        )
        assert url == "http://pmtiles/twi"

    @patch("app.services.tile_service.generate_pmtiles")
    def test_risk_pmtiles(self, mock_generate):
        from app.services.tile_service import generate_risk_pmtiles
        mock_generate.return_value = "http://pmtiles/risk"
        url = generate_risk_pmtiles("p1", b"data")
        mock_generate.assert_called_once_with(
            "p1", b"data",
            raster_name="risk", min_zoom=10, max_zoom=18, colormap="Reds",
        )
        assert url == "http://pmtiles/risk"


# ── Flow lines ────────────────────────────────────────────────────────

class TestGetFlowLinesGeoJSON:
    """Tests for get_flow_lines_geojson."""

    @patch("app.services.tile_service._s3_client")
    def test_found(self, mock_s3_factory, patch_settings):
        """Returns parsed GeoJSON bytes when the object exists."""
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3
        geojson_bytes = json.dumps({"type": "FeatureCollection", "features": []}).encode()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: geojson_bytes)}

        from app.services.tile_service import get_flow_lines_geojson
        result = get_flow_lines_geojson("parcel-456")

        assert result == geojson_bytes
        mock_s3.get_object.assert_called_once_with(
            Bucket="nkz-hydrology",
            Key="pipelines/parcel-456/streams.geojson",
        )

    @patch("app.services.tile_service._s3_client")
    def test_not_found(self, mock_s3_factory, patch_settings):
        """Returns None when the object does not exist."""
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3
        mock_s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        mock_s3.get_object.side_effect = mock_s3.exceptions.NoSuchKey("not found")

        from app.services.tile_service import get_flow_lines_geojson
        assert get_flow_lines_geojson("parcel-none") is None

    @patch("app.services.tile_service._s3_client")
    def test_other_error_returns_none(self, mock_s3_factory, patch_settings):
        """Any non-Key error is caught and returns None."""
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3
        # Set up NoSuchKey on the mock so the except clause runs
        mock_s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        mock_s3.get_object.side_effect = Exception("connection error")

        from app.services.tile_service import get_flow_lines_geojson
        assert get_flow_lines_geojson("parcel-err") is None


# ── pmtiles_exists / get_pmtiles_url ──────────────────────────────────

class TestPMTilesExists:
    @patch("app.services.tile_service._s3_client")
    def test_exists(self, mock_s3_factory, patch_settings):
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3

        from app.services.tile_service import pmtiles_exists
        assert pmtiles_exists("p1", "twi") is True
        mock_s3.head_object.assert_called_once_with(
            Bucket="nkz-hydrology", Key="pmtiles/p1/twi.pmtiles",
        )

    @patch("app.services.tile_service._s3_client")
    def test_not_exists(self, mock_s3_factory, patch_settings):
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3
        mock_s3.head_object.side_effect = Exception("not found")

        from app.services.tile_service import pmtiles_exists
        assert pmtiles_exists("p1", "twi") is False


class TestGetPMTilesURL:
    @patch("app.services.tile_service.pmtiles_exists")
    def test_exists(self, mock_exists, patch_settings):
        mock_exists.return_value = True
        from app.services.tile_service import get_pmtiles_url
        url = get_pmtiles_url("p1", "twi")
        assert url == (
            "https://minio.example.com/nkz-hydrology/pmtiles/p1/twi.pmtiles"
        )

    @patch("app.services.tile_service.pmtiles_exists")
    def test_not_exists(self, mock_exists, patch_settings):
        mock_exists.return_value = False
        from app.services.tile_service import get_pmtiles_url
        assert get_pmtiles_url("p1", "twi") is None


# ── API endpoints via TestClient ──────────────────────────────────────

class TestVisualizationAPI:
    """Integration-style tests for the /visualization endpoints."""

    @patch("app.api.visualization.get_pmtiles_url")
    def test_get_twi_tiles(self, mock_get_url, client):
        mock_get_url.return_value = "http://pmtiles/twi.pmtiles"
        resp = client.get("/api/v1/hydrology/visualization/p1/tiles/twi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pmtiles_url"] == "http://pmtiles/twi.pmtiles"
        assert "status" not in body  # generated → no status field

    @patch("app.api.visualization.get_pmtiles_url")
    def test_get_twi_tiles_not_generated(self, mock_get_url, client):
        mock_get_url.return_value = None
        resp = client.get("/api/v1/hydrology/visualization/p1/tiles/twi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_generated"
        assert "pmtiles_url" in body

    @patch("app.api.visualization.get_pmtiles_url")
    def test_get_risk_tiles_not_generated(self, mock_get_url, client):
        mock_get_url.return_value = None
        resp = client.get("/api/v1/hydrology/visualization/p1/tiles/risk")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_generated"

    @patch("app.api.visualization.get_flow_lines_geojson")
    def test_get_flows_found(self, mock_get_geojson, client):
        fc = {"type": "FeatureCollection", "features": []}
        mock_get_geojson.return_value = json.dumps(fc).encode()
        resp = client.get("/api/v1/hydrology/visualization/p1/flows")
        assert resp.status_code == 200
        assert resp.json() == fc

    @patch("app.api.visualization.get_flow_lines_geojson")
    def test_get_flows_not_found(self, mock_get_geojson, client):
        mock_get_geojson.return_value = None
        resp = client.get("/api/v1/hydrology/visualization/p1/flows")
        assert resp.status_code == 404
        assert "No flow data" in resp.json()["detail"]

    @patch("app.api.visualization.get_flow_lines_geojson")
    def test_check_flows(self, mock_get_geojson, client):
        mock_get_geojson.return_value = b"{}"
        resp = client.get("/api/v1/hydrology/visualization/p1/flows/check")
        assert resp.status_code == 200
        assert resp.json() == {"exists": True}

        mock_get_geojson.return_value = None
        resp = client.get("/api/v1/hydrology/visualization/p1/flows/check")
        assert resp.json() == {"exists": False}
