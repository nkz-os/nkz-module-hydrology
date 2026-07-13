"""
NKZ Water Studio — FIWARE Notification Webhook Receiver

Orion-LD delivers DeviceMeasurement notifications here (target registered by
the setup-parcel subscription: `{api_prefix}/webhooks/fiware-sensors`).

Notifications arrive pod-to-pod WITHOUT JWT/HMAC, so this route carries NO auth
dependency. It is a log-only placeholder — it MUST NOT mutate state and must
never raise on arbitrary/malformed bodies. Sensor-driven recompute is future
work (spec Ronda 2.x).
"""

import logging

from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/fiware-sensors", status_code=204)
async def fiware_sensors(request: Request) -> Response:
    """Receive an NGSI-LD DeviceMeasurement notification (log-only placeholder).

    No auth (Orion posts unauthenticated pod-to-pod). Never mutates state and
    never raises: logs the tenant + entity count and returns 204. The future
    sensor-driven recompute pipeline (Ronda 2.x) will hook in here.
    """
    tenant = request.headers.get("NGSILD-Tenant", "unknown")
    entity_count = 0
    try:
        payload = await request.json()
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                entity_count = len(data)
    except Exception:  # noqa: BLE001 — malformed body must not 500
        logger.warning("fiware-sensors webhook: unparseable body (tenant=%s)", tenant)
        return Response(status_code=204)

    logger.info(
        "fiware-sensors webhook: tenant=%s entities=%d (log-only, Ronda 2.x recompute TODO)",
        tenant,
        entity_count,
    )
    return Response(status_code=204)
