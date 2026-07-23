"""
NKZ Water Studio — Visualization Router

Endpoints for tile URLs, flow lines, and raster-derived visualization assets.
Lazy-imports tile_service to avoid boto3 dependency at import time.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Depends

from app.config import get_settings
from app.middleware import require_auth
from nkz_platform_sdk import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visualization", tags=["Visualization"])


@router.get("/{parcel_id}/overlay/twi")
async def get_twi_overlay(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get the TWI ground-overlay PNG (presigned URL) + WGS84 bounds.

    JSON only — never image bytes (the api-gateway 502s non-JSON). The browser
    fetches the PNG directly from the private MinIO bucket via the presigned URL.
    """
    from app.services.overlay import ensure_twi_overlay, overlay_png_key
    from app.services.tile_service import get_public_url

    bounds = ensure_twi_overlay(parcel_id, ctx.tenant_id)
    if bounds is None:
        return {"url": None, "bounds": None, "status": "not_generated"}
    url = get_public_url(overlay_png_key(parcel_id, ctx.tenant_id))
    return {"url": url, "bounds": bounds, "status": "ok"}


@router.get("/{parcel_id}/flows")
async def get_flows(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get stream network GeoJSON for a parcel."""
    from app.services.tile_service import get_flow_lines_geojson

    geojson = get_flow_lines_geojson(parcel_id, ctx.tenant_id)
    if not geojson:
        raise HTTPException(status_code=404, detail="No flow data — run DEM pipeline first")
    return json.loads(geojson.decode("utf-8"))


@router.get("/{parcel_id}/kpis")
async def get_kpis(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get scenario KPIs for a parcel."""
    from app.services.s3 import get_s3_client

    settings = get_settings()
    s3 = get_s3_client()
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=f"scenarios/{parcel_id}/kpis.json",
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as exc:
        logger.warning("KPIs unavailable for %s: %s", parcel_id, exc)
        return {"baseline": {}, "intervention": {}}
