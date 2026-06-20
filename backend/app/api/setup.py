"""
NKZ Water Studio — Internal Parcel Activation Router

Called by entity-manager with X-Internal-Service-Secret when a user activates
hydrology for a parcel. Frozen contract (mirrors crop-health setup.py):

    POST {api_prefix}/internal/setup-parcel

Auth: X-Internal-Service-Secret only (no JWT).
Body: {"parcel_id": str, "tenant_id": str, "action": "activate"|"deactivate"}

Activate path:
    1. Create placeholder entities via nkz_platform_sdk.ModuleActivation
    2. Ensure DeviceMeasurement subscription via SubscriptionRegistrar

Deactivate/teardown: log-only (actual cleanup in later phases).
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nkz_platform_sdk.activation import ModuleActivation
from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

INTERNAL_SECRET = get_settings().internal_service_secret

# Placeholder entities owned by hydrology (design spec §3.3)
PLACEHOLDER_ENTITIES = [
    {"type": "AgriSoil", "id_suffix": "hydrology-profile"},
    {"type": "WaterBalanceAssessment", "id_suffix": "latest"},
]


class SetupParcelRequest(BaseModel):
    """Request body for /internal/setup-parcel."""
    parcel_id: str
    tenant_id: str
    action: str = "activate"  # "activate" | "deactivate" | "teardown"


@router.post("/setup-parcel", status_code=201)
async def setup_parcel(request: Request, body: SetupParcelRequest):
    """Parcel activation lifecycle endpoint. Called by entity-manager."""
    secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SECRET or secret != INTERNAL_SECRET:
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

    # Activate path
    activation = ModuleActivation(tenant_id=body.tenant_id)
    try:
        result = await activation.ensure_entities(
            parcel_id=parcel_urn, entities=PLACEHOLDER_ENTITIES
        )
    finally:
        await activation.close()

    logger.info(
        "setup-parcel %s tenant=%s: created=%d skipped=%d errors=%d",
        body.parcel_id, body.tenant_id,
        result["created"], result["skipped"], len(result["errors"]),
    )

    if result["errors"] and not (result["created"] or result["skipped"]):
        raise HTTPException(
            status_code=502,
            detail=f"Orion-LD entity creation failed: {result['errors'][:3]}",
        )

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
        "setup-parcel subscription ensure tenant=%s: created=%d skipped=%d errors=%d",
        body.tenant_id,
        sub_result["created"], sub_result["skipped"], len(sub_result["errors"]),
    )

    return {
        "message": "activated",
        "parcel_id": body.parcel_id,
        "created": result["created"],
        "skipped": result["skipped"],
        "entity_ids": result["entity_ids"],
    }
