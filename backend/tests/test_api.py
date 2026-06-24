"""
Tests for NKZ Water Studio Backend
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


class TestHealth:
    """Health endpoint tests."""
    
    def test_healthz_check(self, client):
        """Liveness probe /healthz returns healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data


class TestAPI:
    """API endpoint tests."""
    
    def test_docs_available(self, client):
        """Test OpenAPI docs are available."""
        response = client.get("/api/v1/hydrology/docs")
        # Should return HTML or redirect
        assert response.status_code == 200
    
    def test_openapi_schema(self, client):
        """Test OpenAPI schema is generated."""
        response = client.get("/api/v1/hydrology/openapi.json")
        assert response.status_code == 200
        
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
    
    def test_health_returns_ok(self, client):
        """Health probes work (liveness always, readiness depends on Redis)."""
        response = client.get("/healthz")
        assert response.status_code == 200


class TestAuth:
    """Auth enforcement: gateway headers + HMAC required on protected routes."""

    def test_analyze_requires_tenant_header(self, client):
        """No X-Tenant-ID -> 401 (SDK require_auth rejects missing header)."""
        resp = client.post("/api/v1/hydrology/analyze/urn:ngsi-ld:AgriParcel:p1")
        assert resp.status_code == 401

    def test_analyze_rejects_bad_hmac(self, client, monkeypatch):
        """Gateway headers present but a bogus HMAC signature -> 401 (fail-closed)."""
        monkeypatch.setenv("HMAC_SECRET", "s3cr3t")
        monkeypatch.setenv("REQUIRE_HMAC", "true")
        from app.config import get_settings
        get_settings.cache_clear()
        resp = client.post(
            "/api/v1/hydrology/analyze/urn:ngsi-ld:AgriParcel:p1",
            headers={
                "X-Tenant-ID": "tenant-a",
                "X-User-ID": "u1",
                "X-User-Roles": "Farmer",
                "Authorization": "Bearer tok",
                "X-Auth-Signature": "deadbeef:1",
            },
        )
        assert resp.status_code == 401
        get_settings.cache_clear()  # reset for the rest of the suite
