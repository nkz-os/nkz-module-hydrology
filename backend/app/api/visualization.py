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


@router.get("/{parcel_id}/tiles/twi")
async def get_twi_tiles(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get TWI PMTiles URL for a parcel."""
    from app.services.tile_service import get_pmtiles_url

    url = get_pmtiles_url(parcel_id, ctx.tenant_id, "twi")
    if url:
        return {"pmtiles_url": url}
    return {"pmtiles_url": None, "status": "not_generated"}


@router.get("/{parcel_id}/tiles/risk")
async def get_risk_tiles(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get risk overlay PMTiles URL for a parcel."""
    from app.services.tile_service import get_pmtiles_url

    url = get_pmtiles_url(parcel_id, ctx.tenant_id, "risk")
    if url:
        return {"pmtiles_url": url}
    return {"pmtiles_url": None, "status": "not_generated"}


@router.get("/{parcel_id}/flows")
async def get_flows(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get stream network GeoJSON for a parcel."""
    from app.services.tile_service import get_flow_lines_geojson

    geojson = get_flow_lines_geojson(parcel_id, ctx.tenant_id)
    if not geojson:
        raise HTTPException(status_code=404, detail="No flow data — run DEM pipeline first")
    return json.loads(geojson.decode("utf-8"))


@router.get("/{parcel_id}/flows/check")
async def check_flows_exist(parcel_id: str, ctx: AuthContext = require_auth()):
    """Check whether flow-line data exists for a parcel."""
    from app.services.tile_service import get_flow_lines_geojson

    return {"exists": get_flow_lines_geojson(parcel_id, ctx.tenant_id) is not None}


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
