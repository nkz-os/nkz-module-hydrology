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

    When that pipeline lands, read the entity the canonical way. `DeviceMeasurement`
    inverts the shape used by entity types that carry their readings as attributes:

      - the device is `refDevice.object`, NOT the last segment of the entity id
        (that segment is the measured property name);
      - the reading's name is the VALUE of `controlledProperty`, not an attribute key;
      - its value is in `numValue` or `textValue`, never both;
      - the instant is `dateObserved`, a plain Property, not per-attribute `observedAt`.

    A missing `refDevice` or value means there is nothing safe to persist — skip the
    entity rather than writing a guessed or empty device id.
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
