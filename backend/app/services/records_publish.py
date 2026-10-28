"""Async persistence of hydrology NGSI-LD entities via the SDK OrionClient.

Thin layer over entity_publisher builders. Orion I/O is isolated here so the
builders stay pure and unit-testable without a broker.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from nkz_platform_sdk import OrionClient

logger = logging.getLogger(__name__)


async def publish_hydrology_record(
    tenant_id: str,
    record: dict[str, Any],
    orion: OrionClient | None = None,
) -> dict[str, Any]:
    """Persist one AgriParcelRecord via create_entity (historized).

    Args:
        tenant_id: Request tenant.
        record: Dict from build_hydrology_record.
        orion: Optional injected OrionClient (tests). If None, one is built for the tenant.

    Returns:
        The SDK create_entity result: {"id", "status"}.
    """
    own = orion is None
    if orion is None:
        orion = OrionClient(tenant_id)
    try:
        result = await orion.create_entity(record)
        logger.info("Published AgriParcelRecord tenant=%s id=%s", tenant_id, result.get("id"))
        return result
    finally:
        if own:
            await orion.close()


async def publish_hydrology_zones(
    tenant_id: str,
    zones: list[dict[str, Any]],
    orion: OrionClient | None = None,
) -> dict[str, Any]:
    """Persist AgriParcelZone dicts via upsert_entities_batch (static, in-place).

    One request per zone: a zone polygon can weigh hundreds of KB, so a single
    batch of all zones exceeds the broker's request size limit (413). A zone the
    broker rejects is logged and reported; the other zones are still written.
    No-op (returns skipped) when zones is empty.
    """
    if not zones:
        return {"upserted": 0, "skipped": True}
    own = orion is None
    if orion is None:
        orion = OrionClient(tenant_id)
    upserted = 0
    errors: list[dict[str, Any]] = []
    try:
        for zone in zones:
            try:
                result = await orion.upsert_entities_batch([zone])
            except httpx.HTTPError as exc:
                logger.error("AgriParcelZone not published tenant=%s id=%s: %s",
                             tenant_id, zone.get("id"), exc)
                errors.append({"id": zone.get("id"), "error": str(exc)})
                continue
            upserted += int(result.get("upserted") or 0)
            errors.extend(result.get("errors", []))
        logger.info("Published %d AgriParcelZone tenant=%s upserted=%d errors=%d",
                    len(zones), tenant_id, upserted, len(errors))
        return {"upserted": upserted, "errors": errors}
    finally:
        if own:
            await orion.close()
