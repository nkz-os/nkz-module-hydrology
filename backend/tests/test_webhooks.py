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


def test_webhook_gate_off_by_default(client, monkeypatch):
    """Flag off by default: no secret required, any body still 204."""
    monkeypatch.delenv("NOTIFY_REQUIRE_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    resp = client.post(WEBHOOK, json={"data": []})
    assert resp.status_code == 204


def test_webhook_gate_on_missing_secret_rejected(client, monkeypatch):
    """Flag on + no X-Internal-Service-Secret header -> 401."""
    monkeypatch.setenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "true")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3cr3t")
    resp = client.post(WEBHOOK, json={"data": []})
    assert resp.status_code == 401


def test_webhook_gate_on_wrong_secret_rejected(client, monkeypatch):
    """Flag on + wrong X-Internal-Service-Secret header -> 401."""
    monkeypatch.setenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "1")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3cr3t")
    resp = client.post(
        WEBHOOK, json={"data": []},
        headers={"X-Internal-Service-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_gate_on_correct_secret_accepted(client, monkeypatch):
    """Flag on + correct X-Internal-Service-Secret header -> 204."""
    monkeypatch.setenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "on")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3cr3t")
    resp = client.post(
        WEBHOOK, json={"data": []},
        headers={"X-Internal-Service-Secret": "s3cr3t"},
    )
    assert resp.status_code == 204


def test_webhook_gate_on_empty_configured_secret_fails_closed(client, monkeypatch):
    """Flag on but no INTERNAL_SERVICE_SECRET configured -> fail-closed 401."""
    monkeypatch.setenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "true")
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    resp = client.post(
        WEBHOOK, json={"data": []},
        headers={"X-Internal-Service-Secret": "anything"},
    )
    assert resp.status_code == 401
