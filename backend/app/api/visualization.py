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

    url = get_pmtiles_url(parcel_id, "twi")
    if url:
        return {"pmtiles_url": url}
    settings = get_settings()
    placeholder = f"{settings.minio_public_url}/{settings.minio_bucket}/pmtiles/{parcel_id}/twi.pmtiles"
    return {"pmtiles_url": placeholder, "status": "not_generated"}


@router.get("/{parcel_id}/tiles/risk")
async def get_risk_tiles(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get risk overlay PMTiles URL for a parcel."""
    from app.services.tile_service import get_pmtiles_url

    url = get_pmtiles_url(parcel_id, "risk")
    if url:
        return {"pmtiles_url": url}
    settings = get_settings()
    placeholder = f"{settings.minio_public_url}/{settings.minio_bucket}/pmtiles/{parcel_id}/risk.pmtiles"
    return {"pmtiles_url": placeholder, "status": "not_generated"}


@router.get("/{parcel_id}/flows")
async def get_flows(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get stream network GeoJSON for a parcel."""
    from app.services.tile_service import get_flow_lines_geojson

    geojson = get_flow_lines_geojson(parcel_id)
    if not geojson:
        raise HTTPException(status_code=404, detail="No flow data — run DEM pipeline first")
    return json.loads(geojson.decode("utf-8"))


@router.get("/{parcel_id}/flows/check")
async def check_flows_exist(parcel_id: str, ctx: AuthContext = require_auth()):
    """Check whether flow-line data exists for a parcel."""
    from app.services.tile_service import get_flow_lines_geojson

    return {"exists": get_flow_lines_geojson(parcel_id) is not None}


@router.get("/{parcel_id}/kpis")
async def get_kpis(parcel_id: str, ctx: AuthContext = require_auth()):
    """Get scenario KPIs for a parcel."""
    import boto3

    settings = get_settings()
    s3 = boto3.client("s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=f"scenarios/{parcel_id}/kpis.json",
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return {"baseline": {}, "intervention": {}}
