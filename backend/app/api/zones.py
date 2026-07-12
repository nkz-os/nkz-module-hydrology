"""Hydrology zone endpoints — zonal KPIs and PMTiles URL."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from nkz_platform_sdk import SyncOrionClient, AuthContext

from app.middleware import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parcels", tags=["hydrology-zones"])


@router.get("/{parcel_id}/zones")
def get_parcel_zones(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> list[dict]:
    """Get AgriParcelZone entities with zonal KPIs for a parcel."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entities = orion.query_entities(
            type="AgriParcelZone",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
        )
        zones = []
        for e in entities:
            zone: dict = {"id": e.get("id", ""), "type": e.get("type", "")}
            for key in (
                "nkz:zoneId",
                "nkz:twiMean",
                "nkz:twiRange",
                "nkz:areaHa",
                "nkz:runoffMm",
                "nkz:sedimentYieldTonnes",
                "nkz:soilSaturationPct",
                "nkz:pondViability",
                "nkz:keylineGrade",
            ):
                val = e.get(key)
                if isinstance(val, dict):
                    zone[key.replace("nkz:", "")] = val.get("value")
                else:
                    zone[key.replace("nkz:", "")] = val
            zones.append(zone)
        return zones
    except Exception as e:
        logger.warning("Failed to get parcel zones: %s", e)
        return []


@router.get("/{parcel_id}/pmtiles-url")
def get_pmtiles_url(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Get the public MinIO URL for the TWI PMTiles of this parcel."""
    from app.services.tile_service import twi_pmtiles_key, get_public_url
    key = twi_pmtiles_key(parcel_id, auth.tenant_id)
    url = get_public_url(key)
    return {"url": url, "key": key}
