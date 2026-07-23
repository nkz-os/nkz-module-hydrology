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


def test_get_public_url_is_presigned(presign_settings):
    from app.services import tile_service

    url = tile_service.get_public_url("hydrology/t7/p1/twi.pmtiles")
    parsed = urlparse(url)
    assert parsed.netloc == "minio.robotika.cloud"
    assert "X-Amz-Signature" in url
    assert "hydrology/t7/p1/twi.pmtiles" in url



