"""Tests for the zonal-stats endpoint."""
import io
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from rasterio.warp import transform_geom

from app.api import zonal

X0, Y0, PX = 600000.0, 4700000.0, 10.0


def _tif(arr):
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=20, width=20, count=1,
                       dtype="float32", crs="EPSG:25830",
                       transform=rasterio.transform.from_origin(X0, Y0, PX, PX)) as d:
        d.write(arr.astype("float32"), 1)
    return buf.getvalue()


def _body(n=1):
    utm = {"type": "Polygon", "coordinates": [[[X0 + 1, Y0 - 99], [X0 + 199, Y0 - 99],
                                               [X0 + 199, Y0 - 1], [X0 + 1, Y0 - 1], [X0 + 1, Y0 - 99]]]}
    g = transform_geom("EPSG:25830", "EPSG:4326", utm)
    return zonal.ZonalStatsRequest(zones=[{"zoneId": f"z{i}", "zoneVersion": "v1", "geometry": g} for i in range(n)])


AUTH = SimpleNamespace(tenant_id="acme")


def test_requires_auth():
    app = FastAPI()
    app.include_router(zonal.router)
    r = TestClient(app).post("/parcels/p1/zonal-stats", json={"zones": []})
    assert r.status_code == 401


def test_404_without_twi():
    with patch.object(zonal, "download_raster", return_value=None):
        with pytest.raises(HTTPException) as e:
            zonal.zonal_stats("urn:ngsi-ld:AgriParcel:p1", _body(), auth=AUTH)
    assert e.value.status_code == 404


def test_200_with_faked_minio():
    twi = np.full((20, 20), 5.0)
    twi[:10] = 20.0
    store = {"twi.tif": _tif(twi), "slope.tif": _tif(np.full((20, 20), 2.0))}
    with patch.object(zonal, "download_raster", side_effect=lambda p, t, n: store.get(n)), \
         patch.object(zonal, "SyncOrionClient") as orion:
        orion.return_value.query_entities.return_value = []
        out = zonal.zonal_stats("urn:ngsi-ld:AgriParcel:p1", _body(), auth=AUTH)
    assert out["parcel_id"] == "urn:ngsi-ld:AgriParcel:p1"
    assert out["demSource"] is None
    z = out["zones"][0]
    assert z["zoneId"] == "z0" and z["fidelity"] == "zone_specific"
    assert z["slopeMean"] == 2.0 and z["flowAccumMax"] is None


def test_more_than_20_zones_rejected():
    with pytest.raises(Exception):
        _body(21)
