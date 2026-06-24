"""Async persistence of hydrology NGSI-LD entities via the SDK OrionClient.

Thin layer over entity_publisher builders. Orion I/O is isolated here so the
builders stay pure and unit-testable without a broker.
"""

from __future__ import annotations

import logging
from typing import Any

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

    No-op (returns skipped) when zones is empty.
    """
    if not zones:
        return {"upserted": 0, "skipped": True}
    own = orion is None
    if orion is None:
        orion = OrionClient(tenant_id)
    try:
        result = await orion.upsert_entities_batch(zones)
        logger.info(
            "Published %d AgriParcelZone tenant=%s upserted=%s errors=%d",
            len(zones), tenant_id, result.get("upserted"), len(result.get("errors", [])),
        )
        return result
    finally:
        if own:
            await orion.close()
