"""Tests for /internal/setup-parcel endpoint."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_wrong_secret_returns_401():
    """POST with wrong X-Internal-Service-Secret returns 401."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="activate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "wrong"}, "client": None})()

    with patch("app.api.setup.INTERNAL_SECRET", "real-secret"):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await setup_parcel(req, body)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_activate_calls_sdk_and_returns_201():
    """Activate calls ModuleActivation + SubscriptionRegistrar and returns 201."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="activate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.INTERNAL_SECRET", "s3cr3t"), \
         patch("app.api.setup.ModuleActivation") as MA, \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        MA.return_value.ensure_entities = AsyncMock(
            return_value={
                "created": 2, "skipped": 0, "errors": [],
                "entity_ids": ["urn:ngsi-ld:AgriSoil:t-1:P-1-hydrology-profile"],
            }
        )
        MA.return_value.close = AsyncMock()
        SR.return_value.ensure_all = AsyncMock(
            return_value={"created": 1, "skipped": 0, "errors": []}
        )

        result = await setup_parcel(req, body)

    assert result["message"] == "activated"
    assert result["parcel_id"] == "P-1"
    assert result["created"] == 2
    assert result["skipped"] == 0

    MA.assert_called_once_with(tenant_id="t-1")
    MA.return_value.ensure_entities.assert_awaited_once()
    MA.return_value.close.assert_awaited_once()

    SR.assert_called_once()
    assert SR.call_args.kwargs["module_name"] == "hydrology"
    assert SR.call_args.kwargs["subscriptions"] == [
        {"type": "DeviceMeasurement", "throttling": 30}
    ]
    SR.return_value.ensure_all.assert_awaited_once_with(["t-1"])


@pytest.mark.asyncio
async def test_deactivate_no_sdk_calls():
    """Deactivate does NOT call ModuleActivation or SubscriptionRegistrar."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-2", tenant_id="t-2", action="deactivate")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.INTERNAL_SECRET", "s3cr3t"), \
         patch("app.api.setup.ModuleActivation") as MA, \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        result = await setup_parcel(req, body)

    assert result["message"] == "deactivate"
    assert result["parcel_id"] == "P-2"
    assert result["action"] == "deactivate"

    MA.assert_not_called()
    SR.assert_not_called()


@pytest.mark.asyncio
async def test_teardown_no_sdk_calls():
    """Teardown is also log-only and does NOT call SDK."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-3", tenant_id="t-3", action="teardown")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.INTERNAL_SECRET", "s3cr3t"), \
         patch("app.api.setup.ModuleActivation") as MA, \
         patch("app.api.setup.SubscriptionRegistrar") as SR:

        result = await setup_parcel(req, body)

    assert result["message"] == "teardown"
    assert result["parcel_id"] == "P-3"
    assert result["action"] == "teardown"

    MA.assert_not_called()
    SR.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_action_returns_400():
    """Invalid action returns 400."""
    from app.api.setup import setup_parcel, SetupParcelRequest

    body = SetupParcelRequest(parcel_id="P-1", tenant_id="t-1", action="nuke")
    req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()

    with patch("app.api.setup.INTERNAL_SECRET", "s3cr3t"):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await setup_parcel(req, body)
        assert exc.value.status_code == 400
