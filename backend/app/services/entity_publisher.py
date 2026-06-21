"""
Entity publisher: publish hydrology entities to Orion-LD via SDK.
"""

import json
import logging
from typing import Optional

from nkz_platform_sdk import SyncOrionClient
from app.config import get_settings

logger = logging.getLogger(__name__)


def publish_streams(parcel_id: str, tenant_id: str, streams_geojson: bytes) -> list[str]:
    """Publish stream network as nkz:OpenChannelFlow entities.

    One entity per stream segment.
    """
    settings = get_settings()
    client = SyncOrionClient(tenant_id)
    fc = json.loads(streams_geojson.decode("utf-8"))
    ids = []

    for i, feat in enumerate(fc.get("features", [])):
        entity_id = f"urn:ngsi-ld:OpenChannelFlow:{parcel_id}:stream_{i}"
        entity = {
            "id": entity_id,
            "type": "nkz:OpenChannelFlow",
            "geometry": {"type": "Polygon", "coordinates": [[]]},
            "location": {
                "type": "GeoProperty",
                "value": feat.get("geometry", {}),
            },
            "hasAgriParcel": {
                "type": "Relationship",
                "object": f"urn:ngsi-ld:AgriParcel:{parcel_id}",
            },
            "classification": {
                "type": "Property",
                "value": "stream",
            },
        }
        client.upsert(entity)
        ids.append(entity_id)

    logger.info("Published %d stream entities for parcel %s", len(ids), parcel_id)
    return ids


def publish_h3_twi(
    parcel_id: str, tenant_id: str, h3_data: dict[str, float]
) -> list[str]:
    """Publish TWI H3 cells as individual entities."""
    settings = get_settings()
    client = SyncOrionClient(tenant_id)
    ids = []

    for hex_id, twi_mean in h3_data.items():
        entity_id = f"urn:ngsi-ld:TWI_H3:{parcel_id}:{hex_id}"
        entity = {
            "id": entity_id,
            "type": "TWI_H3",
            "h3Index": {"type": "Property", "value": hex_id},
            "twiMean": {"type": "Property", "value": round(twi_mean, 2)},
            "hasAgriParcel": {
                "type": "Relationship",
                "object": f"urn:ngsi-ld:AgriParcel:{parcel_id}",
            },
        }
        client.upsert(entity)
        ids.append(entity_id)

    logger.info("Published %d TWI H3 entities for parcel %s", len(ids), parcel_id)
    return ids
