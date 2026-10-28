"""Tests for the hydrology Orion persistence layer (OrionClient mocked)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import records_publish
from app.services.entity_publisher import build_hydrology_record, build_hydrology_zones

TENANT = "tenant-a"
PARCEL = "urn:ngsi-ld:AgriParcel:parcel-123"
POLY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
OBSERVED = "2026-06-24T10:00:00Z"


@pytest.mark.asyncio
async def test_publish_record_calls_create_entity():
    record = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY, observed_at=OBSERVED,
        metrics={"twiMean": 5.0}, dem_source="ign",
    )
    fake_orion = MagicMock()
    fake_orion.create_entity = AsyncMock(return_value={"id": record["id"], "status": "created"})

    result = await records_publish.publish_hydrology_record(TENANT, record, orion=fake_orion)

    fake_orion.create_entity.assert_awaited_once_with(record)
    assert result["status"] == "created"
    assert result["id"] == record["id"]


@pytest.mark.asyncio
async def test_publish_zones_empty_skips_batch():
    fake_orion = MagicMock()
    fake_orion.upsert_entities_batch = AsyncMock()

    result = await records_publish.publish_hydrology_zones(TENANT, [], orion=fake_orion)

    fake_orion.upsert_entities_batch.assert_not_awaited()
    assert result == {"upserted": 0, "skipped": True}


@pytest.mark.asyncio
async def test_publish_zones_calls_upsert_batch():
    zones = build_hydrology_zones(
        TENANT, PARCEL, OBSERVED,
        zones=[{"zone_id": "twi-mid", "geometry": POLY, "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    fake_orion = MagicMock()
    fake_orion.upsert_entities_batch = AsyncMock(
        return_value={"upserted": 1, "errors": [], "entity_ids": [z["id"] for z in zones]}
    )

    result = await records_publish.publish_hydrology_zones(TENANT, zones, orion=fake_orion)

    fake_orion.upsert_entities_batch.assert_awaited_once_with(zones)
    assert result["upserted"] == 1


@pytest.mark.asyncio
async def test_publish_zones_one_request_per_zone_and_a_failure_does_not_drop_the_rest():
    # Each zone polygon can be hundreds of KB: one request per zone keeps every
    # request under the broker's payload limit, and one rejected zone keeps the others.
    import httpx

    zones = build_hydrology_zones(
        TENANT, PARCEL, OBSERVED,
        zones=[{"zone_id": f"twi-{i}", "geometry": POLY, "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300} for i in range(3)],
    )
    calls = []

    async def upsert(batch):
        calls.append(batch)
        if batch[0]["id"] == zones[1]["id"]:
            raise httpx.HTTPStatusError("413", request=MagicMock(), response=MagicMock(status_code=413))
        return {"upserted": 1, "errors": [], "entity_ids": [batch[0]["id"]]}

    fake_orion = MagicMock()
    fake_orion.upsert_entities_batch = upsert

    result = await records_publish.publish_hydrology_zones(TENANT, zones, orion=fake_orion)

    assert calls == [[z] for z in zones]
    assert result["upserted"] == 2
    assert [e["id"] for e in result["errors"]] == [zones[1]["id"]]


@pytest.mark.asyncio
async def test_publish_record_uses_default_orion_client_for_tenant():
    """When no orion is passed, the function builds an OrionClient(tenant_id)."""
    record = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY, observed_at=OBSERVED,
        metrics={"twiMean": 5.0}, dem_source="ign",
    )
    fake_orion = MagicMock()
    fake_orion.create_entity = AsyncMock(return_value={"id": "x", "status": "created"})
    fake_orion.close = AsyncMock()

    with patch.object(records_publish, "OrionClient", return_value=fake_orion) as mock_ctor:
        await records_publish.publish_hydrology_record(TENANT, record)
        mock_ctor.assert_called_once_with(TENANT)
