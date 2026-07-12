"""Tests for design API endpoints."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import FastAPI


def test_list_designs_query_uses_or_pipe():
    """list_designs must OR relationship terms with `|`, not `,` (NGSI-LD)."""
    from app.api import designs

    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        designs.list_designs(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))

    _, kwargs = MockOrion.return_value.query_entities.call_args
    q = kwargs["q"]
    assert q == f'(hasAgriParcel=="{pid}"|refAgriParcel=="{pid}")'
    assert "|" in q and "," not in q


def test_list_designs_requires_auth():
    """Without auth headers, list_designs returns 401."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/design?parcel_id=p1")
    assert resp.status_code == 401


def test_create_design_requires_auth():
    """Without auth headers, create_design returns 401."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/design", json={
        "parcel_id": "urn:ngsi-ld:AgriParcel:p1",
        "design_type": "keyline",
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        "label": "Test",
    })
    assert resp.status_code == 401


def test_export_requires_auth():
    """Export endpoint requires auth (checked before format validation)."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/design/xxx/export?format=pdf")
    assert resp.status_code == 401


def test_generation_endpoints_require_auth():
    """All 4 generation endpoints require auth (return 401 without)."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    endpoints = [
        "/design/keyline/generate",
        "/design/pond/score",
        "/design/swale/suggest",
        "/design/check-dam/suggest",
    ]
    for url in endpoints:
        resp = client.post(url, json={"parcel_id": "p1"})
        assert resp.status_code == 401, f"{url} returned {resp.status_code}"
