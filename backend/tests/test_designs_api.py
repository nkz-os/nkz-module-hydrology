"""Tests for design API endpoints."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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


def test_list_designs_queries_both_spec_types():
    """list_designs must query BOTH nkz:WaterStorage and nkz:OpenChannelFlow
    in one call via the comma-separated NGSI-LD typeSelection list (§6.1)."""
    from app.api import designs

    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        designs.list_designs(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))

    _, kwargs = MockOrion.return_value.query_entities.call_args
    assert kwargs["type"] == "nkz:WaterStorage,nkz:OpenChannelFlow"


def test_create_pond_uses_waterstorage_type_and_urn():
    """design_type 'pond' → nkz:WaterStorage with bare-type URN and MTQ capacity."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        designs.create_design(
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="pond",
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                parameters={
                    "capacity": 1500.0,
                    "pondScore": 0.82,
                    "isViable": True,
                    "requiresLining": False,
                },
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    (entity,), _ = MockOrion.return_value.create_entity.call_args
    assert entity["type"] == "nkz:WaterStorage"
    assert entity["id"].startswith("urn:ngsi-ld:WaterStorage:t1:p1:")
    # No nested full parcel URN in the id (audit fix).
    assert "AgriParcel" not in entity["id"]
    assert entity["nkz:capacity"]["value"] == 1500.0
    assert entity["nkz:capacity"]["unitCode"] == "MTQ"
    assert entity["nkz:pondScore"]["value"] == 0.82
    assert entity["nkz:isViable"]["value"] is True
    assert entity["nkz:requiresLining"]["value"] is False


def test_create_keyline_uses_openchannelflow_type_and_grade():
    """design_type 'keyline' → nkz:OpenChannelFlow with nkz:designGrade (%)."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion:
        designs.create_design(
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="keyline",
                geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                parameters={"grade": 0.005},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    (entity,), _ = MockOrion.return_value.create_entity.call_args
    assert entity["type"] == "nkz:OpenChannelFlow"
    assert entity["id"].startswith("urn:ngsi-ld:OpenChannelFlow:t1:p1:")
    assert entity["nkz:designGrade"]["value"] == 0.5


def test_update_keyline_refreshes_design_grade():
    """PUT with a changed grade must PATCH nkz:designGrade with the new % value."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion, \
         patch.object(designs, "httpx") as mock_httpx:
        MockOrion.return_value.get_entity.return_value = {
            "nkz:version": {"value": 3},
        }
        designs.update_design(
            design_id="urn:ngsi-ld:OpenChannelFlow:t1:p1:d1",
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="keyline",
                geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                parameters={"grade": 0.008},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    _, kwargs = mock_httpx.patch.call_args
    attrs = kwargs["json"]
    assert attrs["nkz:designGrade"]["value"] == 0.8
    assert attrs["nkz:version"]["value"] == 4


def test_update_pond_refreshes_typed_attrs_with_unitcode():
    """Pond PUT with capacity must PATCH nkz:capacity carrying MTQ unitCode."""
    from app.api import designs

    with patch.object(designs, "SyncOrionClient") as MockOrion, \
         patch.object(designs, "httpx") as mock_httpx:
        MockOrion.return_value.get_entity.return_value = {
            "nkz:version": {"value": 1},
        }
        designs.update_design(
            design_id="urn:ngsi-ld:WaterStorage:t1:p1:d1",
            req=designs.DesignSaveRequest(
                parcel_id="urn:ngsi-ld:AgriParcel:p1",
                design_type="pond",
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                parameters={"capacity": 2000.0, "isViable": False},
            ),
            auth=SimpleNamespace(tenant_id="t1"),
        )

    _, kwargs = mock_httpx.patch.call_args
    attrs = kwargs["json"]
    assert attrs["nkz:capacity"]["value"] == 2000.0
    assert attrs["nkz:capacity"]["unitCode"] == "MTQ"
    assert attrs["nkz:isViable"]["value"] is False


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


def test_get_design_404_hides_exception_text():
    """get_design 404 must NOT leak the underlying exception (Orion URLs/internals)."""
    from fastapi import HTTPException
    from app.api import designs

    secret = "orion-internal-http://orion:1026/secret-path"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.get_entity.side_effect = RuntimeError(secret)
        with pytest.raises(HTTPException) as exc:
            designs.get_design(design_id="d1", auth=SimpleNamespace(tenant_id="t1"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Design not found"
    assert secret not in str(exc.value.detail)


def test_create_design_500_hides_exception_text():
    """create_design 500 must return a generic detail, not str(e)."""
    from fastapi import HTTPException
    from app.api import designs

    secret = "orion-internal-http://orion:1026/secret-path"
    with patch.object(designs, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.create_entity.side_effect = RuntimeError(secret)
        with pytest.raises(HTTPException) as exc:
            designs.create_design(
                req=designs.DesignSaveRequest(
                    parcel_id="urn:ngsi-ld:AgriParcel:p1",
                    design_type="keyline",
                    geometry={"type": "Point", "coordinates": [0, 0]},
                ),
                auth=SimpleNamespace(tenant_id="t1"),
            )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Internal error"
    assert secret not in str(exc.value.detail)
