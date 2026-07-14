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
from pyproj import Transformer
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

    dem_arr, transform, crs = _read_dem(dem)
    accum_arr, _, _ = _read_dem(accum)

    kl_res = detect_keyline(dem_arr, transform, accum_arr)
    if not kl_res:
        return {"status": "no_keypoint", "detail": "No keypoint found in this parcel"}

    keypoint = kl_res["keypoint"]
    keyline = kl_res["keyline"]
    parallels = generate_keyline_parallels(
        dem, keyline["coordinates"], req.spacing, req.lines, req.grade
    )

    # Reproject all geometry UTM -> WGS84 (parallels computed in UTM first).
    keypoint["coordinates"] = _to_wgs84(keypoint["coordinates"], crs)
    keyline["coordinates"] = _to_wgs84(keyline["coordinates"], crs)
    for p in parallels["parallels"]:
        p["geometry"]["coordinates"] = _to_wgs84(p["geometry"]["coordinates"], crs)

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

    dem_arr, transform, crs = _read_dem(dem)
    # The frontend sends center as WGS84 [lon, lat]; reproject to the raster
    # CRS before inverse-transforming to row/col, or every pick is out of bounds.
    x, y = _from_wgs84([req.center[0], req.center[1]], crs)
    col, row = ~transform * (x, y)
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

    dem_arr, transform, crs = _read_dem(dem)
    accum_arr, _, _ = _read_dem(accum)

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

    # Reproject UTM -> WGS84 after metric lengths/capacities are computed.
    for line in lines:
        line["coordinates"] = _to_wgs84(line["coordinates"], crs)

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
        s3 = get_s3_client()
        settings = get_settings()
        key = stream_network_key(req.parcel_id, auth.tenant_id)
        try:
            streams_geojson = s3.get_object(Bucket=settings.minio_bucket, Key=key)["Body"].read()
        except Exception:
            return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    if not dem:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform, crs = _read_dem(dem)
    streams = json.loads(streams_geojson)
    dams = []

    for feat in streams.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 5:
            continue
        # Sample elevation along the stream, keeping the sampled (x, y) points
        # aligned with the cumulative distances xs.
        xs, zs, sampled = [], [], []
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
                sampled.append((x, y))

        if len(xs) < 5:
            continue
        xs_arr = np.array(xs)
        zs_arr = np.array(zs)
        inflections = find_slope_inflections(xs_arr, zs_arr)
        for pt in inflections:
            # Map the inflection distance back to the nearest sampled point.
            idx = int(np.argmin(np.abs(xs_arr - pt["x"])))
            sx, sy = sampled[idx]
            dams.append({
                "type": "Point",
                "coordinates": _to_wgs84([sx, sy], crs),
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
            return ds.read(1), ds.transform, ds.crs


def _to_wgs84(coords, src_crs):
    """Reproject UTM coordinate(s) to WGS84 lon/lat (EPSG:4326).

    Accepts a single ``[x, y]``/``[x, y, z]`` coordinate or a list of them.
    Output order is (lon, lat, ...) and any trailing z is preserved. Design
    geometry is computed on ETRS89/UTM rasters; every consumer (Cesium
    fromDegreesArray, GPX/KML export, GIS-routing ingest) expects WGS84.
    """
    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)

    def _one(c):
        lon, lat = transformer.transform(c[0], c[1])
        return [lon, lat, *c[2:]]

    if coords and isinstance(coords[0], (list, tuple)):
        return [_one(c) for c in coords]
    return _one(coords)


def _from_wgs84(coord, dst_crs):
    """Reproject a WGS84 lon/lat ``[lon, lat, ...]`` to the raster CRS.

    Inverse of :func:`_to_wgs84`. Client-supplied coordinates (pond center)
    arrive as EPSG:4326 lon/lat and must be projected to the DEM's UTM CRS
    before the raster inverse-affine (``~transform``). Returns ``(x, y)``.
    """
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    x, y = transformer.transform(coord[0], coord[1])
    return x, y


# ── Entity-type mapping (spec §6.1) ────────────────────────────────────
# design_type → (NGSI-LD type, bare type for the URN).
#   pond                       → nkz:WaterStorage   (Polygon storage structure)
#   keyline / swale / check_dam → nkz:OpenChannelFlow (open channel flow line)

_WATER_STORAGE = ("nkz:WaterStorage", "WaterStorage")
_OPEN_CHANNEL_FLOW = ("nkz:OpenChannelFlow", "OpenChannelFlow")


def _entity_type_for(design_type: str) -> tuple[str, str]:
    """Map a design_type to its spec-frozen (ngsi_type, bare_type)."""
    return _WATER_STORAGE if design_type == "pond" else _OPEN_CHANNEL_FLOW


# ── CRUD endpoints ────────────────────────────────────────────────────

@router.get("")
def list_designs(
    parcel_id: str = Query(...),
    auth: AuthContext = require_auth(),
) -> list[dict]:
    """List all hydrology design entities for a parcel.

    Both spec types are fetched in a single call via the NGSI-LD
    typeSelection list — comma IS valid in the ``type`` param (unlike ``q``).
    """
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entities = orion.query_entities(
            type="nkz:WaterStorage,nkz:OpenChannelFlow",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
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
    """Create a hydrology design entity in Orion-LD (spec §6.1-6.3).

    Maps design_type → nkz:WaterStorage (pond) / nkz:OpenChannelFlow
    (keyline/swale/check_dam) and stamps the typed attributes from
    ``req.parameters`` when present.
    """
    design_id = str(uuid.uuid4())
    tenant_id = auth.tenant_id
    ngsi_type, bare_type = _entity_type_for(req.design_type)
    parcel_short = req.parcel_id.rsplit(":", 1)[-1]
    entity = {
        "@context": [
            "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context.jsonld",
            "https://nekazari.robotika.cloud/ngsi-ld-context.json",
        ],
        "id": f"urn:ngsi-ld:{bare_type}:{tenant_id}:{parcel_short}:{design_id}",
        "type": ngsi_type,
        "hasAgriParcel": {"type": "Relationship", "object": req.parcel_id},
        "location": {"type": "GeoProperty", "value": req.geometry},
        "nkz:designType": {"type": "Property", "value": req.design_type},
        "nkz:parameters": {"type": "Property", "value": req.parameters},
        "nkz:version": {"type": "Property", "value": 1},
        "nkz:label": {"type": "Property", "value": req.label},
    }

    params = req.parameters or {}
    if ngsi_type == _WATER_STORAGE[0]:
        if "capacity" in params:
            entity["nkz:capacity"] = {
                "type": "Property", "value": params["capacity"], "unitCode": "MTQ",
            }
        for attr in ("pondScore", "isViable", "requiresLining"):
            if attr in params:
                entity[f"nkz:{attr}"] = {"type": "Property", "value": params[attr]}
    else:  # nkz:OpenChannelFlow
        if "grade" in params:
            # Spec §6.2: designGrade is a percentage; parameters.grade is a ratio.
            entity["nkz:designGrade"] = {"type": "Property", "value": params["grade"] * 100}

    try:
        orion = SyncOrionClient(tenant_id)
        orion.create_entity(entity)
        return {"id": entity["id"], "status": "created"}
    except Exception:
        logger.exception("Failed to create design")
        raise HTTPException(status_code=500, detail="Internal error")


@router.get("/{design_id}")
def get_design(
    design_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Get a single hydrology design entity (id-based, type-agnostic)."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        return orion.get_entity(design_id)
    except Exception:
        logger.exception("Failed to get design %s", design_id)
        raise HTTPException(status_code=404, detail="Design not found")


@router.put("/{design_id}")
def update_design(
    design_id: str,
    req: DesignSaveRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Update a hydrology design entity (increments version).

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
    except Exception:
        logger.exception("Failed to update design %s", design_id)
        raise HTTPException(status_code=500, detail="Internal error")


@router.delete("/{design_id}")
def delete_design(
    design_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Delete a hydrology design entity (id-based, type-agnostic)."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        orion.delete_entity(design_id)
        return {"id": design_id, "status": "deleted"}
    except Exception:
        logger.exception("Failed to delete design %s", design_id)
        raise HTTPException(status_code=500, detail="Internal error")


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
    except Exception:
        logger.exception("Failed to export design %s", design_id)
        raise HTTPException(status_code=404, detail="Design not found")

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
