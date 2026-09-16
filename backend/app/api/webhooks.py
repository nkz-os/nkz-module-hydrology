"""
NKZ Water Studio — FIWARE Notification Webhook Receiver

Orion-LD delivers DeviceMeasurement notifications here (target registered by
the setup-parcel subscription: `{api_prefix}/webhooks/fiware-sensors`).

Notifications arrive pod-to-pod WITHOUT JWT/HMAC, so this route carries a
flag-gated internal-secret check (NOTIFY_REQUIRE_INTERNAL_SECRET, default off)
instead of a JWT dependency. It is a log-only placeholder — it MUST NOT mutate
state and must never raise on arbitrary/malformed bodies. Sensor-driven
recompute is future work (spec Ronda 2.x).
"""

import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _reject_unauthenticated_notify(x_internal_secret: str | None) -> HTTPException | None:
    """401 unless the notification carries the internal secret (flag-gated).

    Two-phase rollout: NOTIFY_REQUIRE_INTERNAL_SECRET stays off until subscription
    creators have converged to carry receiverInfo, then flips on with no code deploy.
    """
    require = os.getenv("NOTIFY_REQUIRE_INTERNAL_SECRET", "").lower() in (
        "1", "true", "yes", "on"
    )
    if not require:
        return None
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if not secret or not hmac.compare_digest(x_internal_secret or "", secret):
        return HTTPException(status_code=401, detail="missing or invalid internal secret")
    return None


@router.post("/fiware-sensors", status_code=204)
async def fiware_sensors(request: Request) -> Response:
    """Receive an NGSI-LD DeviceMeasurement notification (log-only placeholder).

    Auth is a flag-gated internal-secret check (default off), raised before any
    try/except so a 401 is not swallowed into a 500. Never mutates state and
    never raises on arbitrary/malformed bodies: logs the tenant + entity count
    and returns 204. The future sensor-driven recompute pipeline (Ronda 2.x)
    will hook in here.

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
    reject = _reject_unauthenticated_notify(
        request.headers.get("X-Internal-Service-Secret")
    )
    if reject:
        raise reject

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
