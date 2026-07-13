"""Tests for /internal/setup-parcel endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


def _mock_settings(secret="s3cr3t"):
    """Helper: create a mock settings with the given internal_service_secret."""
    s = type("S", (), {"internal_service_secret": secret, "self_url": "http://x",
                        "api_prefix": "/api/v1/hydrology", "orion_ld_url": "http://o",
                        "orion_ld_context": "http://c"})
    return lambda: s


@pytest.mark.asyncio
async def test_wrong_secret_returns_401():
    """POST with wrong X-Internal-Service-Secret returns 401."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="activate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "wrong"}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings("real-secret")):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await setup_parcel(req, body)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_configured_secret_fails_closed():
    """A blank configured internal secret rejects all callers (fail-closed)."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="activate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": ""}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings("")):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await setup_parcel(req, body)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_activate_only_ensures_subscription():
    """Activate ensures the DeviceMeasurement subscription and returns 201; creates NO entities."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="activate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings()), \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        SR.return_value.ensure_all = AsyncMock(
            return_value={"created": 1, "skipped": 0, "errors": []}
        )

        result = await setup_parcel(req, body)

    assert result["message"] == "activated"
    assert result["parcel_id"] == "P-1"
    assert result["subscription"]["created"] == 1

    SR.assert_called_once()
    SR.return_value.ensure_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_deactivate_no_sdk_calls():
    """Deactivate does NOT call SubscriptionRegistrar (log-only)."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-2", tenant_id="t-2", action="deactivate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings()), \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        result = await setup_parcel(req, body)

    assert result["message"] == "deactivate"
    SR.assert_not_called()


@pytest.mark.asyncio
async def test_teardown_no_sdk_calls():
    """Teardown is also log-only."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-3", tenant_id="t-3", action="teardown")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings()), \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        result = await setup_parcel(req, body)

    assert result["message"] == "teardown"
    SR.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_action_returns_400():
    """Invalid action returns 400."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="nuke")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.get_settings", _mock_settings()):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await setup_parcel(req, body)
        assert exc.value.status_code == 400
