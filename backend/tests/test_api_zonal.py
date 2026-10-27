"""Tests for the zonal-stats endpoint."""
import io
from unittest.mock import patch
import hashlib, hmac as _hmac, time
from botocore.exceptions import ClientError

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.warp import transform_geom

from app.api import zonal
from app.main import app

X0, Y0, PX = 600000.0, 4700000.0, 10.0


def _tif(arr):
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=20, width=20, count=1,
                       dtype="float32", crs="EPSG:25830",
                       transform=rasterio.transform.from_origin(X0, Y0, PX, PX)) as d:
        d.write(arr.astype("float32"), 1)
    return buf.getvalue()


def _body_json(n=1):
    utm = {"type": "Polygon", "coordinates": [[[X0 + 1, Y0 - 99], [X0 + 199, Y0 - 99],
                                               [X0 + 199, Y0 - 1], [X0 + 1, Y0 - 1], [X0 + 1, Y0 - 99]]]}
    g = transform_geom("EPSG:25830", "EPSG:4326", utm)
    return {"zones": [{"zoneId": f"z{i}", "zoneVersion": "v1", "geometry": g} for i in range(n)]}


SECRET = "s3cr3t"
URL = "/api/v1/hydrology/parcels/urn:ngsi-ld:AgriParcel:p1/zonal-stats"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", SECRET)
    monkeypatch.setenv("REQUIRE_HMAC", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def _headers(tenant="acme"):
    ts = int(time.time())
    sig = _hmac.new(SECRET.encode(), f"tok|{tenant}|{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Tenant-ID": tenant, "X-User-ID": "u1", "X-User-Roles": "Farmer",
            "Authorization": "Bearer tok", "X-Auth-Signature": f"{sig}:{ts}"}


class FakeS3:
    def __init__(self, store=None, error=None):
        self.store, self.error = store or {}, error

    def get_object(self, Bucket, Key):
        if self.error:
            raise ClientError({"Error": {"Code": self.error}}, "GetObject")
        name = Key.rsplit("/", 1)[-1]
        if name not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.store[name])}


def _post(client, body, s3, url=URL):
    with patch.object(zonal, "get_s3_client", return_value=s3), \
         patch.object(zonal, "SyncOrionClient") as orion:
        orion.return_value.query_entities.return_value = []
        return client.post(url, json=body, headers=_headers())


def _store():
    twi = np.full((20, 20), 5.0)
    twi[:10] = 20.0
    return {"twi.tif": _tif(twi), "slope.tif": _tif(np.full((20, 20), 2.0))}


def test_requires_auth(client):
    assert client.post(URL, json={"zones": []}).status_code == 401


def test_404_without_twi(client):
    assert _post(client, _body_json(), FakeS3()).status_code == 404


def test_502_on_storage_fault(client):
    assert _post(client, _body_json(), FakeS3(error="InternalError")).status_code == 502


def test_200_signed_with_faked_minio(client):
    r = _post(client, _body_json(), FakeS3(_store()))
    assert r.status_code == 200
    out = r.json()
    assert out["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1" and out["demSource"] is None
    z = out["zones"][0]
    assert z["zoneId"] == "z0" and z["fidelity"] == "zone_specific"
    assert z["slopeMean"] == 2.0 and z["flowAccumMax"] is None


def test_more_than_20_zones_422(client):
    assert _post(client, _body_json(21), FakeS3(_store())).status_code == 422


def test_multipolygon_zone(client):
    body = _body_json()
    g = body["zones"][0]["geometry"]
    body["zones"][0]["geometry"] = {"type": "MultiPolygon", "coordinates": [g["coordinates"]]}
    r = _post(client, body, FakeS3(_store()))
    assert r.status_code == 200 and r.json()["zones"][0]["fidelity"] == "zone_specific"


def test_out_of_extent_zone_inherits_parcel(client):
    body = _body_json()
    body["zones"][0]["geometry"] = {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10]]]}
    r = _post(client, body, FakeS3(_store()))
    assert r.status_code == 200 and r.json()["zones"][0]["fidelity"] == "parcel_inherited"


def test_bad_geometry_422_names_zone(client):
    body = _body_json()
    body["zones"][0]["geometry"] = {"type": "Point", "coordinates": [0, 0]}
    r = _post(client, body, FakeS3(_store()))
    assert r.status_code == 422 and "z0" in r.json()["detail"]


def test_bad_zone_does_not_fail_others(client):
    body = _body_json(2)
    body["zones"][1]["geometry"] = {"type": "Polygon", "coordinates": [[[1e9, 1e9], [1e9, 2e9], [2e9, 2e9], [1e9, 1e9]]]}
    r = _post(client, body, FakeS3(_store()))
    assert r.status_code == 200
    assert [z["fidelity"] for z in r.json()["zones"]] == ["zone_specific", "parcel_inherited"]


def test_corrupt_raster_500(client):
    r = _post(client, _body_json(), FakeS3({"twi.tif": b"not a tiff"}))
    assert r.status_code == 500


def test_unsafe_parcel_id_rejected(client):
    r = _post(client, _body_json(), FakeS3(_store()), url="/api/v1/hydrology/parcels/a%22b/zonal-stats")
    assert r.status_code == 422


def test_slope_shape_mismatch_nulls_slope(client):
    st = _store()
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32",
                       crs="EPSG:25830", transform=rasterio.transform.from_origin(X0, Y0, PX, PX)) as d:
        d.write(np.ones((10, 10), "float32"), 1)
    st["slope.tif"] = buf.getvalue()
    r = _post(client, _body_json(), FakeS3(st))
    assert r.status_code == 200 and r.json()["zones"][0]["slopeMean"] is None
