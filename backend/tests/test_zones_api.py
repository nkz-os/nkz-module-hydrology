"""Tests for zones API endpoint."""
from types import SimpleNamespace
from unittest.mock import patch

from nkz_platform_sdk import SyncOrionClient
from fastapi.testclient import TestClient
from fastapi import FastAPI


def test_zones_query_uses_or_pipe():
    """get_parcel_zones must OR relationship terms with `|`, not `,` (NGSI-LD)."""
    from app.api import zones

    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(zones, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        zones.get_parcel_zones(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))

    _, kwargs = MockOrion.return_value.query_entities.call_args
    q = kwargs["q"]
    assert q == f'(hasAgriParcel=="{pid}"|refAgriParcel=="{pid}")'
    assert "|" in q and "," not in q


def test_zones_requires_auth():
    """Without auth, returns 401."""
    from app.api.zones import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/parcels/p1/zones")
    assert resp.status_code == 401



