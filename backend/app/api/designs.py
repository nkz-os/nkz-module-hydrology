"""Hydrology design endpoints — generation, CRUD, export."""
from __future__ import annotations

import io
import json
import logging
import math
import uuid

import numpy as np
from typing import Any

import httpx
import rasterio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from nkz_platform_sdk import SyncOrionClient, AuthContext, inject_fiware_headers

from app.config import get_settings
from app.middleware import require_auth
from app.services.design_generator import (
    download_raster,
    generate_keyline_parallels,
    extract_contour_at_elevation,
    find_slope_inflections,
)
from app.services.gpx_export import geometry_to_gpx, geometry_to_kml
from app.services.keyline import detect_keyline
from app.services.pond_score import pond_score
from app.services.works_design import swale_capacity, check_dam_spacing, check_dam_sediment_retention

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["hydrology-designs"])


# ── Request schemas ────────────────────────────────────────────────────

class KeylineRequest(BaseModel):
    parcel_id: str
    grade: float = 0.005
    spacing: float = 12.0
    lines: int = 7


class PondScoreRequest(BaseModel):
    parcel_id: str
    center: list[float]
    radius: float = 30.0
    depth: float = 2.0


class SwaleSuggestRequest(BaseModel):
    parcel_id: str
    bank_height: float = 1.5
    trench_depth: float = 0.4
    trench_width: float = 1.2


class CheckDamSuggestRequest(BaseModel):
    parcel_id: str
    height: float = 0.6
    width: float = 1.2


class DesignSaveRequest(BaseModel):
    parcel_id: str
    design_type: str
    geometry: dict
    parameters: dict = {}
    label: str = ""


# ── Generation endpoints ──────────────────────────────────────────────

@router.post("/keyline/generate")
def generate_keyline(
    req: KeylineRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Generate keypoint + primary keyline + N parallel lines."""
    from app.services.design_generator import download_raster, generate_keyline_parallels

    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    accum = download_raster(req.parcel_id, auth.tenant_id, "accum.tif")
    if not dem or not accum:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform = _read_dem(dem)
    accum_arr, _ = _read_dem(accum)

    kl_res = detect_keyline(dem_arr, transform, accum_arr)
    if not kl_res:
        return {"status": "no_keypoint", "detail": "No keypoint found in this parcel"}

    keypoint = kl_res["keypoint"]
    keyline = kl_res["keyline"]
    parallels = generate_keyline_parallels(
        dem, keyline["coordinates"], req.spacing, req.lines, req.grade
    )

    return {
        "keypoint": keypoint,
        "keyline": keyline,
        "parallel_lines": parallels["parallels"],
        "request": req.model_dump(),
        "status": "ok",
    }


@router.post("/pond/score")
def score_pond(
    req: PondScoreRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Score a pond site at the given center point."""
    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    if not dem:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform = _read_dem(dem)
    # Sample elevation at the center point to estimate catchment
    col, row = ~transform * (req.center[0], req.center[1])
    col, row = int(col), int(row)
    ny, nx = dem_arr.shape
    if not (0 <= col < nx and 0 <= row < ny):
        return {"status": "out_of_bounds"}

    # Catchment yield: rough estimate from area x runoff depth (100mm default)
    catchment_area_m2 = math.pi * req.radius ** 2
    catchment_yield_m3 = catchment_area_m2 * 0.1  # 100mm runoff
    earthwork_m3 = catchment_area_m2 * req.depth

    ps = pond_score(
        catchment_yield_m3=catchment_yield_m3,
        earthwork_m3=max(100, earthwork_m3),
        reliability_pct=80.0,
        ksat_mmh=15.0,
    )

    return {
        "pondScore": ps["pondScore"],
        "isViable": ps["isViable"],
        "factors": ps["factors"],
        "request": req.model_dump(),
        "status": "ok",
    }


@router.post("/swale/suggest")
def suggest_swales(
    req: SwaleSuggestRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Auto-suggest swale lines above the keyline."""
    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    accum = download_raster(req.parcel_id, auth.tenant_id, "accum.tif")
    if not dem or not accum:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform = _read_dem(dem)
    accum_arr, _ = _read_dem(accum)

    # Find keypoint to determine keyline elevation
    kl_res = detect_keyline(dem_arr, transform, accum_arr)
    if not kl_res or "keypoint" not in kl_res:
        return {"status": "no_keypoint", "detail": "No keypoint found"}

    keypoint_z = kl_res["keypoint"]["coordinates"][2]
    # Suggest swales from keyline elevation up to ridge
    mid_elev = keypoint_z + (dem_arr.max() - keypoint_z) * 0.5
    lines = extract_contour_at_elevation(dem, mid_elev, max_length_m=200)

    # Calculate capacity for each swale
    capacities = []
    for line in lines:
        coords = line["coordinates"]
        length_m = sum(
            math.hypot(c2[0] - c1[0], c2[1] - c1[1])
            for c1, c2 in zip(coords, coords[1:])
        )
        sc = swale_capacity(req.bank_height, req.trench_width, length_m)
        capacities.append(sc)

    return {
        "lines": lines,
        "spacing_m": req.bank_height / max(0.01, (dem_arr.max() - keypoint_z) / 100) if len(lines) > 1 else 50,
        "count": len(lines),
        "capacities": capacities,
        "request": req.model_dump(),
        "status": "ok" if lines else "no_contours",
    }


@router.post("/check-dam/suggest")
def suggest_check_dams(
    req: CheckDamSuggestRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Auto-suggest check dam locations on the stream network."""
    streams_geojson = download_raster(req.parcel_id, auth.tenant_id, "streams.geojson")
    if not streams_geojson:
        # Try S3 key for GeoJSON (not a TIFF)
        from app.services.s3 import get_s3_client
        from app.services.tile_service import stream_network_key
        import botocore.exceptions as boto_err
        s3 = get_s3_client()
        settings = get_settings()
        key = stream_network_key(req.parcel_id, auth.tenant_id)
        try:
            streams_geojson = s3.get_object(Bucket=settings.minio_bucket, Key=key)["Body"].read()
        except (boto_err.ClientError, Exception):
            return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    if not dem:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform = _read_dem(dem)
    streams = json.loads(streams_geojson)
    dams = []

    for feat in streams.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 5:
            continue
        # Sample elevation along the stream
        xs, zs = [], []
        for i, (x, y) in enumerate(coords):
            col, row = ~transform * (x, y)
            col, row = int(col), int(row)
            if 0 <= col < dem_arr.shape[1] and 0 <= row < dem_arr.shape[0]:
                if xs:
                    dist = math.hypot(x - coords[i-1][0], y - coords[i-1][1])
                    xs.append(xs[-1] + dist)
                else:
                    xs.append(0.0)
                zs.append(float(dem_arr[row, col]))

        if len(xs) < 5:
            continue
        xs_arr = np.array(xs)
        zs_arr = np.array(zs)
        inflections = find_slope_inflections(xs_arr, zs_arr)
        for pt in inflections:
            dams.append({
                "type": "Point",
                "coordinates": [coords[0][0], coords[0][1]],  # simplified
                "channel_slope_pct": round(pt["slope_after"], 1),
                "spacing_to_next_m": round(check_dam_spacing(pt["slope_after"], req.height), 1),
                "sediment_retention_t": round(check_dam_sediment_retention(req.height, req.width)),
            })

    return {
        "dams": dams,
        "request": req.model_dump(),
        "status": "ok" if dams else "no_inflections",
    }


def _read_dem(dem_bytes: bytes) -> tuple:
    with io.BytesIO(dem_bytes) as f:
        with rasterio.open(f) as ds:
            return ds.read(1), ds.transform


# ── CRUD endpoints ────────────────────────────────────────────────────

@router.get("")
def list_designs(
    parcel_id: str = Query(...),
    auth: AuthContext = require_auth(),
) -> list[dict]:
    """List all HydrologyDesign entities for a parcel."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entities = orion.query_entities(
            type="nkz:HydrologyDesign",
            q=f'hasAgriParcel=="{parcel_id}",refAgriParcel=="{parcel_id}"',
        )
        return entities
    except Exception as e:
        logger.warning("Failed to list designs: %s", e)
        return []


@router.post("")
def create_design(
    req: DesignSaveRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Create a new HydrologyDesign entity in Orion-LD."""
    design_id = str(uuid.uuid4())
    tenant_id = auth.tenant_id
    entity = {
        "@context": [
            "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context.jsonld",
            "https://nekazari.robotika.cloud/ngsi-ld-context.json",
        ],
        "id": f"urn:ngsi-ld:nkz:HydrologyDesign:{tenant_id}:{req.parcel_id}:{design_id}",
        "type": "nkz:HydrologyDesign",
        "hasAgriParcel": {"type": "Relationship", "object": req.parcel_id},
        "location": {"type": "GeoProperty", "value": req.geometry},
        "nkz:designType": {"type": "Property", "value": req.design_type},
        "nkz:parameters": {"type": "Property", "value": req.parameters},
        "nkz:version": {"type": "Property", "value": 1},
        "nkz:label": {"type": "Property", "value": req.label},
    }
    try:
        orion = SyncOrionClient(tenant_id)
        orion.create_entity(entity)
        return {"id": entity["id"], "status": "created"}
    except Exception as e:
        logger.exception("Failed to create design")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{design_id}")
def get_design(
    design_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Get a single HydrologyDesign entity."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        return orion.get_entity(design_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{design_id}")
def update_design(
    design_id: str,
    req: DesignSaveRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Update a HydrologyDesign entity (increments version).

    Uses PATCH /ngsi-ld/v1/entities/{id}/attrs via httpx since
    SyncOrionClient lacks append_entity_attrs (async-only method).
    """
    try:
        orion = SyncOrionClient(auth.tenant_id)
        current = orion.get_entity(design_id)
        version = (current.get("nkz:version", {}).get("value", 0) or 0) + 1

        attrs = {
            "location": {"type": "GeoProperty", "value": req.geometry},
            "nkz:parameters": {"type": "Property", "value": req.parameters},
            "nkz:version": {"type": "Property", "value": version},
            "nkz:label": {"type": "Property", "value": req.label},
        }
        settings = get_settings()
        orion_url = settings.orion_ld_url.rstrip("/")
        url = f"{orion_url}/ngsi-ld/v1/entities/{design_id}/attrs"
        headers = inject_fiware_headers(auth.tenant_id, content_type="application/json")
        resp = httpx.patch(url, json=attrs, headers=headers, timeout=10)
        resp.raise_for_status()
        return {"id": design_id, "version": version, "status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{design_id}")
def delete_design(
    design_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Delete a HydrologyDesign entity."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        orion.delete_entity(design_id)
        return {"id": design_id, "status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Export endpoint ────────────────────────────────────────────────────

@router.get("/{design_id}/export")
def export_design(
    design_id: str,
    format: str = Query("geojson", pattern="^(geojson|gpx|kml)$"),
    auth: AuthContext = require_auth(),
):
    """Export a design in GPX, KML, or GeoJSON format."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entity = orion.get_entity(design_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    geom = (entity.get("location", {}) or {}).get("value", {})
    if not geom:
        raise HTTPException(status_code=404, detail="Design has no geometry")

    name = (entity.get("nkz:label", {}) or {}).get("value", "Hydrology Design")

    if format == "gpx":
        from fastapi.responses import Response
        gpx = geometry_to_gpx(geom, name)
        return Response(content=gpx, media_type="application/gpx+xml")
    elif format == "kml":
        from fastapi.responses import Response
        kml = geometry_to_kml(geom, name)
        return Response(content=kml, media_type="application/vnd.google-earth.kml+xml")
    else:
        return {"type": "Feature", "geometry": geom, "properties": {"name": name}}
