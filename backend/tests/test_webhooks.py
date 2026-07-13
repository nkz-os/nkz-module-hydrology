"""Tests for the FIWARE sensors webhook receiver.

Orion-LD delivers DeviceMeasurement notifications pod-to-pod (no JWT/HMAC).
The route must accept any JSON body, never raise, and return 204.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

WEBHOOK = "/api/v1/hydrology/webhooks/fiware-sensors"


@pytest.fixture
def client():
    return TestClient(app)


def test_webhook_valid_notification_returns_204(client):
    """A well-formed NGSI-LD notification returns 204 (no auth required)."""
    body = {
        "subscriptionId": "urn:ngsi-ld:Subscription:1",
        "data": [
            {"id": "urn:ngsi-ld:DeviceMeasurement:1", "type": "DeviceMeasurement"},
            {"id": "urn:ngsi-ld:DeviceMeasurement:2", "type": "DeviceMeasurement"},
        ],
    }
    resp = client.post(WEBHOOK, json=body, headers={"NGSILD-Tenant": "tenant-a"})
    assert resp.status_code == 204


def test_webhook_no_auth_header_still_accepted(client):
    """No Authorization / HMAC header — still 204 (Orion is unauthenticated)."""
    resp = client.post(WEBHOOK, json={"data": []})
    assert resp.status_code == 204


def test_webhook_malformed_json_does_not_raise(client):
    """A malformed / non-JSON body must not raise — still 204."""
    resp = client.post(
        WEBHOOK,
        content=b"not-json{",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 204


def test_webhook_arbitrary_shapes_do_not_raise(client):
    """Unexpected JSON shapes (list, string, missing data) never raise."""
    for body in ([1, 2, 3], "hello", {"unexpected": True}, {"data": "nope"}):
        resp = client.post(WEBHOOK, json=body)
        assert resp.status_code == 204
