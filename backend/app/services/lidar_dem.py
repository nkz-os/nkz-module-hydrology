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

# Resample gate: native 0.5 m LiDAR DTMs are kept only for small parcels
# (microtopography matters and the cell count stays small).  Larger parcels
# are resampled so the geolibre-wasm breach/flow engine stays responsive.
_LIDAR_RESAMPLE_AREA_HA = 10.0
_LIDAR_RESAMPLE_CELLSIZE_M = 2.0


def lidar_target_cellsize(area_ha: float) -> float | None:
    """Target output cellsize (m) for a LiDAR DTM, or None for native 0.5 m."""
    if area_ha >= _LIDAR_RESAMPLE_AREA_HA:
        return _LIDAR_RESAMPLE_CELLSIZE_M
    return None


@dataclass
class LidarAsset:
    """A completed LiDAR layer for a parcel."""

    asset_id: str
    parcel_urn: str
    date_observed: str
    dtm_url: str


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
        dtm_url=str(_prop(latest, "dtmUrl") or ""),
    )


def _dtm_s3_key(asset: LidarAsset) -> str:
    """Derive the S3 key of the DTM from the DigitalAsset dtmUrl.

    The public URL is ``{minio_public_base}/{bucket}/{key}``, e.g.
    ``https://minio.robotika.cloud/lidar-tilesets/<prefix>/dtm.tif``.  We
    read the key out of the URL instead of assuming ``{asset_id}/dtm.tif``
    because historical layers upload under the FULL job URN prefix
    (``urn:ngsi-ld:DataProcessingJob:<id>/dtm.tif``) while newer ones use the
    short id — the URL is the single source of truth.
    """
    if "/lidar-tilesets/" in asset.dtm_url:
        return asset.dtm_url.split("/lidar-tilesets/", 1)[1]
    # Fallback: no bucket in URL (should not happen) — assume short-id prefix
    return f"{asset.asset_id}/dtm.tif"


def fetch_dtm_bytes(asset: LidarAsset) -> bytes:
    """Read the DTM GeoTIFF from the internal MinIO endpoint."""
    s3 = get_s3_client()
    resp = s3.get_object(Bucket=LIDAR_TILESETS_BUCKET, Key=_dtm_s3_key(asset))
    return resp["Body"].read()
