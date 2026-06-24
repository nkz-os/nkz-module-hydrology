"""
NKZ Water Studio — Internal Parcel Activation Router

Called by entity-manager with X-Internal-Service-Secret when a user activates
hydrology for a parcel. Frozen contract (mirrors crop-health setup.py):

    POST {api_prefix}/internal/setup-parcel

Auth: X-Internal-Service-Secret only (no JWT).
Body: {"parcel_id": str, "tenant_id": str, "action": "activate"|"deactivate"}

Activate path:
    1. Ensure DeviceMeasurement subscription via SubscriptionRegistrar

Deactivate/teardown: log-only (actual cleanup in later phases).
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

# NOTE (Ronda 2.2): hydrology creates NO placeholder entities at activation.
# AgriParcelRecord/AgriParcelZone are published only when the DEM pipeline runs
# (real data), not at setup.


class SetupParcelRequest(BaseModel):
    """Request body for /internal/setup-parcel."""
    parcel_id: str
    tenant_id: str
    action: str = "activate"  # "activate" | "deactivate" | "teardown"


@router.post("/setup-parcel", status_code=201)
async def setup_parcel(request: Request, body: SetupParcelRequest):
    """Parcel activation lifecycle endpoint. Called by entity-manager."""
    internal_secret = get_settings().internal_service_secret
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not internal_secret or secret != internal_secret:
        logger.warning(
            "Unauthorized internal setup-parcel call from %s", request.client
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    if body.action not in ("activate", "deactivate", "teardown"):
        raise HTTPException(status_code=400, detail="Invalid action")

    parcel_urn = body.parcel_id
    if not parcel_urn.startswith("urn:ngsi-ld:AgriParcel:"):
        parcel_urn = f"urn:ngsi-ld:AgriParcel:{parcel_urn}"

    # Deactivate / teardown: log-only in Fase 0
    if body.action in ("deactivate", "teardown"):
        logger.info(
            "%s hydrology for parcel %s (tenant=%s)",
            body.action, parcel_urn, body.tenant_id,
        )
        return {
            "message": body.action,
            "parcel_id": body.parcel_id,
            "action": body.action,
        }

    # Activate path: ensure the DeviceMeasurement subscription only.
    # Hydrology creates NO entities at activation — AgriParcelRecord/Zone are
    # published only when the DEM pipeline runs (real data), not at setup.
    settings = get_settings()
    notification_url = f"{settings.self_url}{settings.api_prefix}/webhooks/fiware-sensors"
    registrar = SubscriptionRegistrar(
        orion_url=settings.orion_ld_url,
        notification_url=notification_url,
        subscriptions=[{"type": "DeviceMeasurement", "throttling": 30}],
        module_name="hydrology",
        context_url=settings.orion_ld_context,
    )
    sub_result = await registrar.ensure_all([body.tenant_id])
    logger.info(
        "setup-parcel activate tenant=%s: created=%d skipped=%d errors=%d",
        body.tenant_id,
        sub_result["created"], sub_result["skipped"], len(sub_result["errors"]),
    )

    return {
        "message": "activated",
        "parcel_id": body.parcel_id,
        "subscription": {
            "created": sub_result["created"],
            "skipped": sub_result["skipped"],
            "errors": sub_result["errors"][:3],
        },
    }
