"""LiDAR DTM discovery + fetch for hydrology (cross-module integration).

The lidar module publishes one ``DigitalAsset`` NGSI-LD entity per processed
point cloud, with derived rasters (DTM/DSM/CHM at 0.5 m) in the MinIO bucket
``lidar-tilesets`` under key ``{asset_id}/dtm.tif``.

Cross-module contract (2026-09-02):
- Discovery: tenant-scoped Orion-LD query on DigitalAsset
  (``assetCategory=="LiDAR";hasAgriParcel==<urn>;processingStatus=="completed"``).
- Artifacts: INTERNAL S3 read of bucket ``lidar-tilesets``. NEVER fetch the
  public ``dtmUrl`` (minio.robotika.cloud) from a pod — hairpin NAT makes the
  public endpoint unreachable in-cluster.
- CRS: the DTM is in the native CRS of the flight (usually a metric UTM, e.g.
  EPSG:25830). ``utm.reproject_grid_to_utm`` reads the CRS from the GeoTIFF,
  so no degree-vs-metric assumption is needed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from nkz_platform_sdk import OrionClient

from app.services.s3 import get_s3_client

logger = logging.getLogger(__name__)

LIDAR_TILESETS_BUCKET = "lidar-tilesets"


@dataclass
class LidarAsset:
    """A completed LiDAR layer for a parcel."""

    asset_id: str
    parcel_urn: str
    date_observed: str


def _prop(entity: dict, name: str):
    value = entity.get(name)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _parcel_urn(parcel_id: str) -> str:
    if parcel_id.startswith("urn:"):
        return parcel_id
    return f"urn:ngsi-ld:AgriParcel:{parcel_id}"


async def find_latest_lidar_asset(
    tenant_id: str, parcel_id: str
) -> Optional[LidarAsset]:
    """Latest completed LiDAR DigitalAsset with a DTM for the parcel.

    Returns None when the parcel has no usable LiDAR layer (caller falls back
    to eu-elevation). Tenant scoping comes from the Orion NGSILD-Tenant header.
    """
    orion = OrionClient(tenant_id)
    try:
        entities = await orion.query_entities(
            type="DigitalAsset",
            q=(
                'assetCategory=="LiDAR"'
                f';hasAgriParcel=="{_parcel_urn(parcel_id)}"'
                ';processingStatus=="completed"'
            ),
            limit=50,
        )
        await orion.close()
    except Exception:
        logger.warning("DigitalAsset query failed — falling back to eu-elevation", exc_info=True)
        return None

    candidates = [
        e
        for e in entities
        if _prop(e, "dtmUrl") and _prop(e, "processingStatus") == "completed"
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda e: str(_prop(e, "dateObserved") or ""))
    entity_id = str(latest.get("id", ""))
    return LidarAsset(
        asset_id=entity_id.split(":")[-1],
        parcel_urn=_parcel_urn(parcel_id),
        date_observed=str(_prop(latest, "dateObserved") or ""),
    )


def fetch_dtm_bytes(asset: LidarAsset) -> bytes:
    """Read the DTM GeoTIFF from the internal MinIO endpoint."""
    s3 = get_s3_client()
    resp = s3.get_object(
        Bucket=LIDAR_TILESETS_BUCKET, Key=f"{asset.asset_id}/dtm.tif"
    )
    return resp["Body"].read()
