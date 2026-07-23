"""
NKZ Water Studio — Tile Service

Flow-line retrieval from MinIO + presigned URL helper.

TWI visualization uses the PNG ground-overlay (see overlay.py), NOT PMTiles.
PMTiles generation was removed: it had no consumer (the viewer renders the PNG
overlay) and cost CPU + storage on every pipeline run. Reintroduce only if a
multi-parcel tile pyramid (Fase 4 — Water Story) actually needs it.

All MinIO object keys are tenant-scoped (hermeticity): hydrology/{tenant}/{parcel}/...
"""
import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def _s3_client():
    """Create a boto3 S3 client configured from app settings (delegates to the
    shared helper that normalizes the MinIO endpoint URL)."""
    from app.services.s3 import get_s3_client
    return get_s3_client()


def parcel_short(parcel_id: str) -> str:
    """Stable short id from a parcel URN (for object keys)."""
    return parcel_id.rsplit(":", 1)[-1]


# Backwards-compatible alias for existing internal callers/tests.
_parcel_short = parcel_short


def stream_network_key(parcel_id: str, tenant_id: str) -> str:
    """MinIO object key for a stream network GeoJSON file (tenant-scoped)."""
    return f"hydrology/{tenant_id}/{_parcel_short(parcel_id)}/streams.geojson"


# ── Flow lines retrieval ──────────────────────────────────────────────

def get_flow_lines_geojson(parcel_id: str, tenant_id: str) -> Optional[bytes]:
    """Get stream network GeoJSON from MinIO.

    Returns:
        Raw GeoJSON bytes, or ``None`` if the file does not exist.
    """
    s3 = _s3_client()
    settings = get_settings()
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=stream_network_key(parcel_id, tenant_id),
        )
        return resp["Body"].read()
    except s3.exceptions.NoSuchKey:
        logger.info("No flow lines for parcel %s", parcel_id)
        return None
    except Exception as exc:
        logger.warning("Error fetching flow lines for %s: %s", parcel_id, exc)
        return None


def _presign_get(key: str) -> str:
    """Presigned S3v4 GET URL for an object key, signed against the public host."""
    from app.services.s3 import get_presign_client
    settings = get_settings()
    return get_presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.minio_bucket, "Key": key},
        ExpiresIn=settings.presign_expiry_seconds,
    )


def get_public_url(key: str) -> str:
    """Presigned GET URL for an object key.

    The tenant bucket is private (no anonymous policy), so a naked
    ``{public}/{bucket}/{key}`` URL 403s. Returns a short-lived S3v4-presigned URL
    signed against the public MinIO host so a browser can fetch it directly.
    """
    return _presign_get(key)
