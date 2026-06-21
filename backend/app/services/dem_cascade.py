"""
DEM cascade fetcher: LiDAR → PNOA → IGN → Copernicus.
Caches results in MinIO by parcel centroid.
"""

import hashlib
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

PNOA_TEMPLATE = "https://servicios.idee.es/wcs-inspire/pnoa/1.0.0/{z}/{x}/{y}.tif"
IGN_MDT_TEMPLATE = "https://mapas.ign.es/wcs/MDT02/1.0.0?service=WCS&version=2.0.1&request=GetCoverage&coverageid=MDT02&format=image/tiff&subset=X({xmin},{xmax})&subset=Y({ymin},{ymax})&subset=Z(0)"
COPERNICUS_URL = "https://services.sentinel-hub.com/ogc/wcs/1.0.0/DEM"


def _centroid_key(lat: float, lon: float) -> str:
    """Deterministic cache key from centroid."""
    raw = f"{lat:.4f}:{lon:.4f}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def fetch_dem(lat: float, lon: float, parcel_id: str) -> bytes:
    """Fetch best available DEM for a parcel centroid.

    Cascade: LiDAR → PNOA → IGN → Copernicus.
    Checks MinIO cache first.
    """
    settings = get_settings()
    cache_key = f"dem/{_centroid_key(lat, lon)}.tif"

    # Check cache
    cached = await _minio_get(settings, cache_key)
    if cached:
        logger.info("DEM cache hit for %s", parcel_id)
        return cached

    # Cascade
    providers = [
        ("LiDAR module", lambda: _try_lidar(parcel_id, settings)),
        ("PNOA", lambda: _try_pnoa(lat, lon)),
        ("IGN MDT", lambda: _try_ign(lat, lon)),
        ("Copernicus", lambda: _try_copernicus(lat, lon)),
    ]

    for name, fn in providers:
        dem = await fn()
        if dem:
            logger.info("DEM fetched from %s for %s (%d bytes)", name, parcel_id, len(dem))
            await _minio_put(settings, cache_key, dem)
            return dem

    raise RuntimeError(f"No DEM source available for parcel {parcel_id}")


async def _try_lidar(parcel_id: str, settings) -> Optional[bytes]:
    """Check LiDAR module MinIO bucket for user-uploaded DEM."""
    import boto3
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        key = f"dtm/{parcel_id}/dtm.tif"
        resp = s3.get_object(Bucket=settings.minio_bucket, Key=key)
        return resp["Body"].read()
    except Exception:
        return None


async def _try_pnoa(lat: float, lon: float) -> Optional[bytes]:
    """Fetch PNOA tile (WCS). Placeholder: return None for now."""
    logger.debug("PNOA fetch not implemented for Fase 1")
    return None


async def _try_ign(lat: float, lon: float) -> Optional[bytes]:
    """Fetch IGN MDT02 tile."""
    # Approximate 1km tile from centroid
    xmin, xmax = lon - 0.01, lon + 0.01
    ymin, ymax = lat - 0.01, lat + 0.01
    url = IGN_MDT_TEMPLATE.format(xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.debug("IGN fetch failed: %s", e)
        return None


async def _try_copernicus(lat: float, lon: float) -> Optional[bytes]:
    """Fetch Copernicus GLO-30."""
    # Fase 1 placeholder
    logger.debug("Copernicus fetch not implemented for Fase 1")
    return None


async def _minio_get(settings, key: str) -> Optional[bytes]:
    """Get from MinIO cache."""
    import boto3
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        resp = s3.get_object(Bucket=settings.minio_bucket, Key=key)
        return resp["Body"].read()
    except Exception:
        return None


async def _minio_put(settings, key: str, data: bytes):
    """Store in MinIO cache."""
    import boto3
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        s3.put_object(Bucket=settings.minio_bucket, Key=key, Body=data)
    except Exception as e:
        logger.warning("MinIO cache write failed: %s", e)
