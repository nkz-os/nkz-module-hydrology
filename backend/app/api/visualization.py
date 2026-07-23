"""
NKZ Water Studio — Visualization Router.

TWI ground-overlay (presigned PNG + WGS84 bounds) and the stream-network
GeoJSON. Scenario comparison lives at ``/parcels/{id}/scenarios``
(``scenario_compute``) — the old ``/visualization/{id}/kpis`` S3-read dead-end
was removed in Phase 1.2. Lazy-imports tile_service to keep boto3 out of import
time.
"""
import json

from fastapi import APIRouter, HTTPException

from app.middleware import require_auth
from nkz_platform_sdk import AuthContext

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
