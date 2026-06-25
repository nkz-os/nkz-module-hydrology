"""Hydrology design endpoints — generation, CRUD, export."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from nkz_platform_sdk import SyncOrionClient, AuthContext, inject_fiware_headers

from app.config import get_settings
from app.middleware import require_auth
from app.services.design_generator import (
    generate_keyline_parallels,
    extract_contour_at_elevation,
    find_slope_inflections,
)
from app.services.gpx_export import geometry_to_gpx, geometry_to_kml

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
def generate_keyline(req: KeylineRequest) -> dict:
    """Generate keypoint + primary keyline + N parallel lines."""
    return {
        "keypoint": {"type": "Point", "coordinates": [0, 0, 0]},
        "keyline": {"type": "LineString", "coordinates": []},
        "parallel_lines": [],
        "request": req.model_dump(),
        "status": "not_implemented",
    }


@router.post("/pond/score")
def score_pond(req: PondScoreRequest) -> dict:
    """Score a pond site at the given center point."""
    return {
        "pondScore": 0.0,
        "isViable": False,
        "factors": {},
        "request": req.model_dump(),
        "status": "not_implemented",
    }


@router.post("/swale/suggest")
def suggest_swales(req: SwaleSuggestRequest) -> dict:
    """Auto-suggest swale lines above the keyline."""
    return {
        "lines": [],
        "spacing_m": 0,
        "count": 0,
        "request": req.model_dump(),
        "status": "not_implemented",
    }


@router.post("/check-dam/suggest")
def suggest_check_dams(req: CheckDamSuggestRequest) -> dict:
    """Auto-suggest check dam locations on the stream network."""
    return {
        "dams": [],
        "request": req.model_dump(),
        "status": "not_implemented",
    }


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
