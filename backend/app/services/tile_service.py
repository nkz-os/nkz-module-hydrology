"""
NKZ Water Studio — Tile Service

PMTiles generation (TWI, risk rasters) and flow line retrieval from MinIO.
Uses geolibre-wasm write_pmtiles for conversion.
"""

import json
import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def _s3_client():
    """Create a boto3 S3 client configured from app settings (delegates to the
    shared helper that normalizes the MinIO endpoint URL)."""
    from app.services.s3 import get_s3_client
    return get_s3_client()


def _pmtiles_key(parcel_id: str, raster_name: str = "twi") -> str:
    """MinIO object key for a PMTiles file."""
    return f"pmtiles/{parcel_id}/{raster_name}.pmtiles"


def stream_network_key(parcel_id: str) -> str:
    """MinIO object key for a stream network GeoJSON file."""
    return f"pipelines/{parcel_id}/streams.geojson"


# ── PMTiles generation ────────────────────────────────────────────────

def generate_pmtiles(
    parcel_id: str,
    raster_data: bytes,
    raster_name: str = "twi",
    min_zoom: int = 10,
    max_zoom: int = 18,
    colormap: str = "viridis",
) -> str:
    """Convert a single-band raster to PMTiles via geolibre-wasm and upload to MinIO.

    Args:
        parcel_id: Parcel identifier used in the MinIO key.
        raster_data: Raw GeoTIFF bytes of the raster to convert.
        raster_name: Logical name (e.g. ``"twi"``, ``"risk"``).
        min_zoom: Minimum zoom level for the PMTiles pyramid.
        max_zoom: Maximum zoom level.
        colormap: Matplotlib colormap name applied during conversion.

    Returns:
        Public URL of the uploaded PMTiles file.

    Raises:
        RuntimeError: If the geolibre tool fails or produces no output.
    """
    input_name = f"{raster_name}.tif"
    output_name = f"{raster_name}.pmtiles"

    from app.services.geolibre_engine import GeoLibreEngine
    engine = GeoLibreEngine()
    pmtiles = engine.write_pmtiles(raster_data, colormap=colormap,
                                    min_zoom=min_zoom, max_zoom=max_zoom)

    # Upload to MinIO
    key = _pmtiles_key(parcel_id, raster_name)
    s3 = _s3_client()
    s3.put_object(
        Bucket=get_settings().minio_bucket,
        Key=key,
        Body=pmtiles,
        ContentType="application/vnd.pmtiles",
    )

    settings = get_settings()
    public_url = f"{settings.minio_public_url}/{settings.minio_bucket}/{key}"
    logger.info(
        "PMTiles %s for parcel %s: %s (%d bytes)",
        raster_name, parcel_id, public_url, len(pmtiles),
    )
    return public_url


def generate_twi_pmtiles(
    parcel_id: str,
    twi_raster: bytes,
    min_zoom: int = 10,
    max_zoom: int = 18,
) -> str:
    """Convenience wrapper to generate TWI PMTiles with viridis colormap."""
    return generate_pmtiles(
        parcel_id, twi_raster,
        raster_name="twi",
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        colormap="viridis",
    )


def generate_risk_pmtiles(
    parcel_id: str,
    risk_raster: bytes,
    min_zoom: int = 10,
    max_zoom: int = 18,
) -> str:
    """Generate risk-overlay PMTiles with a red-yellow colormap."""
    return generate_pmtiles(
        parcel_id, risk_raster,
        raster_name="risk",
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        colormap="Reds",
    )


# ── Flow lines retrieval ──────────────────────────────────────────────

def get_flow_lines_geojson(parcel_id: str) -> Optional[bytes]:
    """Get stream network GeoJSON from MinIO.

    Returns:
        Raw GeoJSON bytes, or ``None`` if the file does not exist.
    """
    s3 = _s3_client()
    settings = get_settings()
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=stream_network_key(parcel_id),
        )
        return resp["Body"].read()
    except s3.exceptions.NoSuchKey:
        logger.info("No flow lines for parcel %s", parcel_id)
        return None
    except Exception as exc:
        logger.warning("Error fetching flow lines for %s: %s", parcel_id, exc)
        return None


def pmtiles_exists(parcel_id: str, raster_name: str = "twi") -> bool:
    """Check whether a PMTiles file already exists in MinIO."""
    s3 = _s3_client()
    settings = get_settings()
    try:
        s3.head_object(Bucket=settings.minio_bucket, Key=_pmtiles_key(parcel_id, raster_name))
        return True
    except Exception:
        return False


def get_pmtiles_url(parcel_id: str, raster_name: str = "twi") -> Optional[str]:
    """Get the public URL for an existing PMTiles file.

    Returns ``None`` if the file does not exist in MinIO.
    """
    if not pmtiles_exists(parcel_id, raster_name):
        return None
    settings = get_settings()
    return (
        f"{settings.minio_public_url}/{settings.minio_bucket}/"
        f"pmtiles/{parcel_id}/{raster_name}.pmtiles"
    )
