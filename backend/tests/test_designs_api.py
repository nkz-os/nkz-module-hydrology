"""Tests for design API endpoints."""
from fastapi.testclient import TestClient
from fastapi import FastAPI


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


def test_generation_endpoints_return_stub():
    """All 4 generation endpoints should return 200 with status field."""
    from app.api.designs import router
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    endpoints = [
        ("/design/keyline/generate",
         {"parcel_id": "p1", "grade": 0.005, "spacing": 12, "lines": 7}),
        ("/design/pond/score",
         {"parcel_id": "p1", "center": [0, 0], "radius": 30, "depth": 2}),
        ("/design/swale/suggest",
         {"parcel_id": "p1", "bank_height": 1.5, "trench_depth": 0.4, "trench_width": 1.2}),
        ("/design/check-dam/suggest",
         {"parcel_id": "p1", "height": 0.6, "width": 1.2}),
    ]
    for url, body in endpoints:
        resp = client.post(url, json=body)
        assert resp.status_code == 200, f"{url} returned {resp.status_code}"
        assert "status" in resp.json(), f"{url} missing status"
