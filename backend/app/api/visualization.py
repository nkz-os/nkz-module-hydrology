"""
NKZ Water Studio — Visualization Router

Endpoints for tile URLs, flow lines, and raster-derived visualization assets.
"""

import json
import logging

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.tile_service import (
    generate_twi_pmtiles,
    generate_risk_pmtiles,
    get_flow_lines_geojson,
    pmtiles_exists,
    get_pmtiles_url,
    generate_pmtiles,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visualization", tags=["Visualization"])


# ── TWI tiles ─────────────────────────────────────────────────────────

@router.get("/{parcel_id}/tiles/twi")
async def get_twi_tiles(parcel_id: str):
    """Get the TWI PMTiles URL for a parcel.

    Returns the existing PMTiles URL if already generated, otherwise triggers
    generation using the raster stored at the standard MinIO path.
    """
    url = get_pmtiles_url(parcel_id, "twi")
    if url:
        return {"pmtiles_url": url}

    # Not yet generated — the caller should first enqueue a DEM pipeline job
    # (POST /api/v1/hydrology/analyze/{parcel_id}) which produces the TWI
    # raster and publishes it to MinIO.  For now return a placeholder so the
    # frontend can still reference the expected path.
    settings = get_settings()
    placeholder = (
        f"{settings.minio_public_url}/{settings.minio_bucket}/"
        f"pmtiles/{parcel_id}/twi.pmtiles"
    )
    return {
        "pmtiles_url": placeholder,
        "status": "not_generated",
        "message": "Trigger DEM pipeline via POST /analyze/{parcel_id} first",
    }


@router.get("/{parcel_id}/tiles/risk")
async def get_risk_tiles(parcel_id: str):
    """Get the risk-overlay PMTiles URL for a parcel."""
    url = get_pmtiles_url(parcel_id, "risk")
    if url:
        return {"pmtiles_url": url}

    settings = get_settings()
    placeholder = (
        f"{settings.minio_public_url}/{settings.minio_bucket}/"
        f"pmtiles/{parcel_id}/risk.pmtiles"
    )
    return {
        "pmtiles_url": placeholder,
        "status": "not_generated",
    }


# ── Flow lines ────────────────────────────────────────────────────────

@router.get("/{parcel_id}/flows")
async def get_flows(parcel_id: str):
    """Get stream network GeoJSON for a parcel."""
    geojson = get_flow_lines_geojson(parcel_id)
    if not geojson:
        raise HTTPException(
            status_code=404,
            detail="No flow data for parcel — run DEM pipeline first",
        )
    return json.loads(geojson.decode("utf-8"))


@router.get("/{parcel_id}/flows/check")
async def check_flows_exist(parcel_id: str):
    """Check whether flow-line data exists for a parcel."""
    geojson = get_flow_lines_geojson(parcel_id)
    return {"exists": geojson is not None}
