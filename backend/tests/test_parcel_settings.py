"""Per-parcel calculation settings: store and API."""
import hashlib
import hmac as _hmac
import io
import json
import time
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.main import app
from app.services import parcel_settings

SECRET = "s3cr3t"
PID = "urn:ngsi-ld:AgriParcel:p-1"
URL = f"/api/v1/hydrology/parcels/{PID}/settings"


class FakeS3:
    def __init__(self):
        self.store = {}

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.store[Key] = Body


@pytest.fixture
def s3():
    fake = FakeS3()
    with patch.object(parcel_settings, "get_s3_client", return_value=fake):
        yield fake


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", SECRET)
    monkeypatch.setenv("REQUIRE_HMAC", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def _headers(role, tenant="tenant-a"):
    ts = int(time.time())
    sig = _hmac.new(SECRET.encode(), f"tok|{tenant}|{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Tenant-ID": tenant, "X-User-ID": "u-1", "X-User-Roles": role,
            "Authorization": "Bearer tok", "X-Auth-Signature": f"{sig}:{ts}"}


def test_default_when_absent(s3):
    s = parcel_settings.load_settings("tenant-a", PID)
    assert (s.mode, s.return_period_years, s.is_default) == ("storm", 10, True)
    assert s.updated_by is None and s.updated_at is None


def test_save_and_load_roundtrip_records_user_and_time(s3):
    saved = parcel_settings.save_settings("tenant-a", PID, "retention", 25, "u-1")
    assert "hydrology/tenant-a/p-1/settings.json" in s3.store
    loaded = parcel_settings.load_settings("tenant-a", PID)
    assert loaded == saved
    assert (loaded.mode, loaded.return_period_years, loaded.is_default) == ("retention", 25, False)
    assert loaded.updated_by == "u-1" and loaded.updated_at


def test_put_forbidden_for_farmer_and_settings_unchanged(client, s3):
    parcel_settings.save_settings("tenant-a", PID, "storm", 10, "u-0")
    before = dict(s3.store)
    r = client.put(URL, json={"mode": "retention", "return_period_years": 100},
                   headers=_headers("Farmer"))
    assert r.status_code == 403
    assert s3.store == before


def test_put_allowed_for_technical_consultant(client, s3):
    r = client.put(URL, json={"mode": "retention", "return_period_years": 25},
                   headers=_headers("TechnicalConsultant"))
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "retention" and body["return_period_years"] == 25
    assert body["is_default"] is False and body["updated_by"] == "u-1"
    g = client.get(URL, headers=_headers("Farmer"))
    assert g.status_code == 200 and g.json()["mode"] == "retention"


def test_put_rejects_unknown_mode_and_period(client, s3):
    h = _headers("TenantAdmin")
    assert client.put(URL, json={"mode": "flood", "return_period_years": 10}, headers=h).status_code == 422
    assert client.put(URL, json={"mode": "storm", "return_period_years": 50}, headers=h).status_code == 422
    assert s3.store == {}
