"""Tests for zones API endpoint."""
from unittest.mock import patch

from nkz_platform_sdk import SyncOrionClient
from fastapi.testclient import TestClient
from fastapi import FastAPI


def test_zones_requires_auth():
    """Without auth, returns 401."""
    from app.api.zones import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/parcels/p1/zones")
    assert resp.status_code == 401


def test_pmtiles_url_requires_auth():
    """Without auth, returns 401."""
    from app.api.zones import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/parcels/p1/pmtiles-url")
    assert resp.status_code == 401
