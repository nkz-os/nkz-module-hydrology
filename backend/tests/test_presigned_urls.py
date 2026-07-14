"""Presigned PMTiles URLs — tenant bucket is private, so naked public URLs 403.

URLs MUST be S3v4-presigned against the PUBLIC MinIO host (the host is embedded
in the signature). not_generated paths MUST return a null URL, never a guessed one.
"""
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import pytest


@pytest.fixture
def presign_settings(monkeypatch):
    """Fake creds so boto3 can sign offline; public host is minio.robotika.cloud."""
    monkeypatch.setenv("MINIO_ACCESS_KEY", "fake-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "fake-secret")
    monkeypatch.setenv("MINIO_PUBLIC_URL", "https://minio.robotika.cloud")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_presign_client_uses_public_endpoint(presign_settings):
    from app.services.s3 import get_presign_client
    client = get_presign_client()
    assert client.meta.endpoint_url == "https://minio.robotika.cloud"


def test_get_pmtiles_url_is_presigned_against_public_host(presign_settings):
    from app.services import tile_service

    with patch.object(tile_service, "pmtiles_exists", return_value=True):
        url = tile_service.get_pmtiles_url(
            "urn:ngsi-ld:AgriParcel:p1", tenant_id="t7", raster_name="twi"
        )
    assert url is not None
    parsed = urlparse(url)
    assert parsed.netloc == "minio.robotika.cloud"
    assert "X-Amz-Signature" in url
    assert "hydrology/t7/p1/twi.pmtiles" in url


def test_get_pmtiles_url_none_when_missing(presign_settings):
    from app.services import tile_service

    with patch.object(tile_service, "pmtiles_exists", return_value=False):
        url = tile_service.get_pmtiles_url(
            "urn:ngsi-ld:AgriParcel:p1", tenant_id="t7", raster_name="twi"
        )
    assert url is None


def test_get_public_url_is_presigned(presign_settings):
    from app.services import tile_service

    url = tile_service.get_public_url("hydrology/t7/p1/twi.pmtiles")
    parsed = urlparse(url)
    assert parsed.netloc == "minio.robotika.cloud"
    assert "X-Amz-Signature" in url
    assert "hydrology/t7/p1/twi.pmtiles" in url


def test_generate_pmtiles_returns_object_key(presign_settings):
    """Worker path must NOT presign — it returns the bare object key."""
    from app.services import tile_service

    fake_engine = SimpleNamespace(write_pmtiles=lambda *a, **k: b"PMTILES")
    with patch("app.services.geolibre_engine.GeoLibreEngine", return_value=fake_engine), \
         patch.object(tile_service, "_s3_client") as mock_client:
        result = tile_service.generate_pmtiles(
            "urn:ngsi-ld:AgriParcel:p1", b"raster", tenant_id="t7", raster_name="twi"
        )
    assert result == "hydrology/t7/p1/twi.pmtiles"
    mock_client.return_value.put_object.assert_called_once()


# ── API layer ─────────────────────────────────────────────────────────

def test_visualization_twi_not_generated_returns_null(presign_settings):
    import asyncio
    from app.api import visualization
    from app.services import tile_service

    with patch.object(tile_service, "get_pmtiles_url", return_value=None):
        result = asyncio.run(
            visualization.get_twi_tiles("p1", ctx=SimpleNamespace(tenant_id="t7"))
        )
    assert result == {"pmtiles_url": None, "status": "not_generated"}


def test_visualization_risk_not_generated_returns_null(presign_settings):
    import asyncio
    from app.api import visualization
    from app.services import tile_service

    with patch.object(tile_service, "get_pmtiles_url", return_value=None):
        result = asyncio.run(
            visualization.get_risk_tiles("p1", ctx=SimpleNamespace(tenant_id="t7"))
        )
    assert result == {"pmtiles_url": None, "status": "not_generated"}


def test_visualization_twi_generated_returns_presigned(presign_settings):
    import asyncio
    from app.api import visualization
    from app.services import tile_service

    with patch.object(tile_service, "get_pmtiles_url", return_value="https://minio.robotika.cloud/x?X-Amz-Signature=abc"):
        result = asyncio.run(
            visualization.get_twi_tiles("p1", ctx=SimpleNamespace(tenant_id="t7"))
        )
    assert result == {"pmtiles_url": "https://minio.robotika.cloud/x?X-Amz-Signature=abc"}


def test_zones_pmtiles_url_null_when_missing(presign_settings):
    from app.api import zones
    from app.services import tile_service

    with patch.object(tile_service, "pmtiles_exists", return_value=False):
        result = zones.get_pmtiles_url("urn:ngsi-ld:AgriParcel:p1", auth=SimpleNamespace(tenant_id="t7"))
    assert result["url"] is None
    assert result["status"] == "not_generated"
    assert result["key"] == "hydrology/t7/p1/twi.pmtiles"


def test_zones_pmtiles_url_presigned_when_exists(presign_settings):
    from app.api import zones
    from app.services import tile_service

    with patch.object(tile_service, "pmtiles_exists", return_value=True):
        result = zones.get_pmtiles_url("urn:ngsi-ld:AgriParcel:p1", auth=SimpleNamespace(tenant_id="t7"))
    parsed = urlparse(result["url"])
    assert parsed.netloc == "minio.robotika.cloud"
    assert "X-Amz-Signature" in result["url"]
    assert result["key"] == "hydrology/t7/p1/twi.pmtiles"
