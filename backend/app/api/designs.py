"""Hydrology design endpoints — generation, CRUD, export."""
from __future__ import annotations

import functools
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
from pydantic import BaseModel, Field
from nkz_platform_sdk import SyncOrionClient, AuthContext, inject_fiware_headers

from app.config import get_settings
from app.middleware import require_auth
from app.services.design_generator import (
    download_raster,
    extract_contour_at_elevation,
    find_slope_inflections,
)
from app.services.gpx_export import geometry_to_gpx, geometry_to_kml
from app.services.hydro_record import nkz_attr
from app.services.keyline import (
    MAX_LINE_GRADE, analysis_grid, detect_keyline, detect_keypoints, keyline_layout,
)
from app.services.pond_score import pond_score
from app.services.works_design import swale_capacity, check_dam_spacing, check_dam_sediment_retention
from app.services.compliance import requires_water_permit, breach_risk_class, PERMIT_THRESHOLDS_M3

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["hydrology-designs"])


# ── Request schemas ────────────────────────────────────────────────────

class KeylineRequest(BaseModel):
    parcel_id: str
    grade: float = Field(0.005, gt=0)
    spacing: float = Field(12.0, gt=0)
    lines: int | None = Field(None, ge=0)  # rows of lines out from the keylines; None = as far as the terrain allows
    min_line_m: float = Field(100.0, gt=0)  # shorter traced lines are dropped


class PondScoreRequest(BaseModel):
    parcel_id: str
    center: list[float]
    radius: float = 30.0
    depth: float = 2.0
    # Basin authority code (CH_Ebro, CH_Segura, ...) for the permit-threshold
    # compliance check. Auto-detection from coordinates needs a CHX polygon
    # layer (not bundled) — the caller selects it; "default" applies the
    # 5000 m³/year rule.
    basin: str = "default"


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

# Keyline needs a DEM fine enough to resolve a 0.5 % contour.
MAX_KEYLINE_CELL_M = 5.0


def _parcel_polygon(parcel_id: str, tenant_id: str):
    """Parcel polygon (WGS84 shapely geometry) from Orion, or None if it has none.

    Raises HTTP 502 when the broker cannot be read.
    """
    from shapely.geometry import shape

    try:
        ent = SyncOrionClient(tenant_id).get_entity(parcel_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("parcel %s: Orion read failed: %s", parcel_id, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"status": "orion_unavailable", "detail": "Parcel could not be read from the broker"},
        )
    loc = (ent or {}).get("location")
    geom = loc.get("value") if isinstance(loc, dict) and "value" in loc else loc
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    try:
        poly = shape(geom)
    except Exception:  # noqa: BLE001
        return None
    return None if poly.is_empty else poly


def _polygonal(geom):
    """The polygonal part of `geom` made valid (a self-crossing ring becomes
    the polygons it encloses), or None when no area is left."""
    import shapely
    from shapely.geometry import MultiPolygon

    parts = [p for p in shapely.get_parts(shapely.make_valid(geom))
             for p in (shapely.get_parts(p) if p.geom_type == "MultiPolygon" else [p])]
    polys = [p for p in parts if p.geom_type == "Polygon" and not p.is_empty and p.area > 0]
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


@router.post("/keyline/generate")
def generate_keyline(
    req: KeylineRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    """Keypoints of the valleys in the parcel, their keylines and lines traced at grade."""
    from rasterio import features
    from rasterio.warp import transform_geom
    from shapely.geometry import mapping, shape
    from app.services.design_generator import download_raster

    dem = download_raster(req.parcel_id, auth.tenant_id, "breached.tif")
    accum = download_raster(req.parcel_id, auth.tenant_id, "accum.tif")
    if not dem or not accum:
        return {"status": "no_data", "detail": "Run DEM pipeline first"}

    dem_arr, transform, crs = _read_raster_nan(dem)
    accum_arr, _, _ = _read_raster_nan(accum)
    # Cell sizes, spacing and grades are in metres: a DEM in degrees (or with
    # no CRS) would pass the cell-size check below and trace nonsense.
    if crs is None or not crs.is_projected:
        return {"status": "no_data", "detail": "DEM is not in a projected (metric) CRS"}

    cell_m = max(abs(transform.a), abs(transform.e))
    if cell_m > MAX_KEYLINE_CELL_M:
        return {
            "status": "terrain_too_coarse",
            "detail": f"DEM cell size {cell_m:.1f} m exceeds {MAX_KEYLINE_CELL_M:.0f} m",
            "cell_size_m": cell_m,
            "max_cell_size_m": MAX_KEYLINE_CELL_M,
        }

    parcel_wgs = _parcel_polygon(req.parcel_id, auth.tenant_id)
    if parcel_wgs is None:
        return {"status": "no_data", "detail": "Parcel has no polygon"}
    parcel_utm = _polygonal(shape(transform_geom("EPSG:4326", crs, mapping(parcel_wgs))))
    if parcel_utm is None:
        return {"status": "no_data", "detail": "Parcel polygon is not a valid area"}
    # Analysis runs on a field-scale grid with nodata gaps filled
    # (see keyline.ANALYSIS_CELL_M / NODATA_FILL_MAX_M).
    dem_arr, accum_arr, transform = analysis_grid(dem_arr, transform, accum_arr)
    parcel_mask = features.rasterize(
        [(mapping(parcel_utm), 1)], out_shape=dem_arr.shape,
        transform=transform, fill=0, dtype="uint8",
    ).astype(bool) & np.isfinite(dem_arr)

    kps = detect_keypoints(dem_arr, transform, accum_arr, parcel_mask)
    if not kps:
        return {"status": "no_keypoint", "detail": "No keypoint found in this parcel"}

    result = keyline_layout(
        dem_arr, transform, parcel_mask, parcel_utm, kps, req.spacing,
        grade=req.grade, max_lines=req.lines, min_line_m=req.min_line_m, flow_accum=accum_arr,
    )
    layout = result["lines"]
    if result["coverage_truncated"]:
        logger.warning(
            "keyline layout for parcel %s (tenant %s) stopped early (%s): "
            "%d seeds gave no guide, %d lines, spacing %.1f m, grade %.4f",
            req.parcel_id, auth.tenant_id, result["stopped_by"], result["failed_seeds"],
            len(layout), req.spacing, req.grade,
        )

    def _line_wgs(g) -> dict:
        return {"type": "LineString", "coordinates": _to_wgs84([list(c) for c in g.coords], crs)}

    def _metrics(p) -> dict:
        return {"grade": round(p["grade"], 5), "max_grade_20m": round(p["max_grade_20m"], 5)}

    keypoints = [
        {"type": "Point", "coordinates": _to_wgs84([kp["x"], kp["y"], kp["z"]], crs)}
        for kp in kps
    ]
    # Keylines are the layout's "keyline" entries, grouped by valley; every
    # line carries the grade measured on the terrain (see keyline_layout).
    per_valley = [[p for p in layout if p["direction"] == "keyline" and p["valley"] == i]
                  for i in range(len(kps))]
    keyline_entries = [p for pcs in per_valley for p in pcs]
    main = max(per_valley[0], key=lambda p: p["geometry"].length) if per_valley[0] else None
    parallels = [
        {"geometry": _line_wgs(p["geometry"]), "direction": p["direction"], **_metrics(p)}
        for p in layout
        if p["direction"] != "keyline"
    ]
    return {
        "keypoint": keypoints[0],
        "keyline": _line_wgs(main["geometry"]) if main else None,
        "keyline_metrics": _metrics(main) if main else None,
        "keypoints": keypoints,
        "keylines": [_line_wgs(p["geometry"]) for p in keyline_entries],
        "keylines_metrics": [_metrics(p) for p in keyline_entries],
        "parallel_lines": parallels,
        "max_line_grade": MAX_LINE_GRADE,
        "coverage_truncated": result["coverage_truncated"],
        "coverage_pct": round(result["coverage_pct"], 1),
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

    # Compliance (Phase 2.1, revised): the CHX permit threshold compares the
    # pond's STORAGE CAPACITY (π·r²·depth), NOT a runoff-yield figure.
    # Storage-capacity thresholds are a real CHX basis for small balsas and are
    # geometrically computable without an annual-precipitation source (which the
    # platform does not expose). The earlier yield-based check (pond footprint ×
    # 100 mm) grossly under-reported and could advise "no permit" when one was
    # required. See docs/MODELS.md §8.
    # ASSUMPTION: downstream exposure defaults to False (no infrastructure layer);
    # basin auto-detection needs a CHX polygon asset (deferred).
    storage_capacity_m3 = catchment_area_m2 * req.depth  # cylindrical upper bound
    slope_pct = _local_slope_pct(dem_arr, row, col, transform)
    requires_permit = requires_water_permit(storage_capacity_m3, req.basin)
    permit_threshold = PERMIT_THRESHOLDS_M3.get(req.basin, PERMIT_THRESHOLDS_M3["default"])
    breach = breach_risk_class(storage_capacity_m3, slope_pct, has_downstream_exposure=False)
    compliance = {
        "basis": "storage_capacity",
        "basin": req.basin,
        "storageCapacityM3": round(storage_capacity_m3, 1),
        "requiresPermit": requires_permit,
        "permitThresholdM3": permit_threshold,
        "localSlopePct": round(slope_pct, 1),
        "breachRisk": breach,
        "downstreamExposure": {
            "hasExposure": False,
            "affectedBuildings": 0,
            "affectedRoads": 0,
            "affectedStreams": 0,
        },
        "disclaimer": (
            "Estimate based on storage capacity; not legal advice. "
            "Verify with your CHX basin authority before building."
        ),
    }

    return {
        "pondScore": ps["pondScore"],
        "isViable": ps["isViable"],
        "factors": ps["factors"],
        "compliance": compliance,
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


def _read_raster_nan(raster_bytes: bytes) -> tuple:
    """First band as float64 with the nodata value (and NaN) as NaN."""
    with io.BytesIO(raster_bytes) as f:
        with rasterio.open(f) as ds:
            arr = ds.read(1).astype("float64")
            if ds.nodata is not None and not math.isnan(ds.nodata):
                arr[arr == ds.nodata] = np.nan
            return arr, ds.transform, ds.crs


def _local_slope_pct(arr, row, col, transform) -> float:
    """Local terrain slope (%) at a pixel via 3x3 finite difference (UTM metres)."""
    ny, nx = arr.shape
    if not (1 <= row < ny - 1 and 1 <= col < nx - 1):
        return 0.0
    pixel_m = abs(transform.a) or 1.0
    dzdx = (float(arr[row, col + 1]) - float(arr[row, col - 1])) / (2.0 * pixel_m)
    dzdy = (float(arr[row + 1, col]) - float(arr[row - 1, col])) / (2.0 * pixel_m)
    return math.hypot(dzdx, dzdy) * 100.0


@functools.lru_cache(maxsize=16)
def _transformer_to_wgs84(src_crs: str) -> Transformer:
    # Building a Transformer costs ~20 ms; a keyline pattern converts
    # hundreds of lines.
    return Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)


def _to_wgs84(coords, src_crs):
    """Reproject UTM coordinate(s) to WGS84 lon/lat (EPSG:4326).

    Accepts a single ``[x, y]``/``[x, y, z]`` coordinate or a list of them.
    Output order is (lon, lat, ...) and any trailing z is preserved. Design
    geometry is computed on ETRS89/UTM rasters; every consumer (Cesium
    fromDegreesArray, GPX/KML export, GIS-routing ingest) expects WGS84.
    """
    if not coords:
        return coords

    transformer = _transformer_to_wgs84(str(src_crs))

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


def _derived_attrs(design_type: str, parameters: dict | None) -> dict:
    """Typed NGSI-LD attributes derived from ``parameters`` (spec §6.2).

    Single source of truth for both create and update — each attribute is
    emitted only when its source parameter is present.
    """
    params = parameters or {}
    attrs: dict[str, dict] = {}
    ngsi_type, _ = _entity_type_for(design_type)
    if ngsi_type == _WATER_STORAGE[0]:
        if "capacity" in params:
            attrs["nkz:capacity"] = {
                "type": "Property", "value": params["capacity"], "unitCode": "MTQ",
            }
        for attr in ("pondScore", "isViable", "requiresLining"):
            if attr in params:
                attrs[f"nkz:{attr}"] = {"type": "Property", "value": params[attr]}
    else:  # nkz:OpenChannelFlow
        if "grade" in params:
            # Spec §6.2: designGrade is a percentage; parameters.grade is a ratio.
            attrs["nkz:designGrade"] = {"type": "Property", "value": params["grade"] * 100}
    return attrs


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
            get_settings().context_url,
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

    entity.update(_derived_attrs(req.design_type, req.parameters))

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
        version = (nkz_attr(current, "version") or 0) + 1

        attrs = {
            "location": {"type": "GeoProperty", "value": req.geometry},
            "nkz:parameters": {"type": "Property", "value": req.parameters},
            "nkz:version": {"type": "Property", "value": version},
            "nkz:label": {"type": "Property", "value": req.label},
        }
        # Re-derive typed attrs (nkz:designGrade / nkz:capacity, ...) so they
        # never drift from nkz:parameters after an update (spec §6.2).
        attrs.update(_derived_attrs(req.design_type, req.parameters))
        settings = get_settings()
        orion_url = settings.orion_ld_url.rstrip("/")
        url = f"{orion_url}/ngsi-ld/v1/entities/{design_id}/attrs"
        # Attribute fragment carries no @context → application/json + Link.
        # inject_fiware_headers only adds Link when the CONTEXT_URL env var is
        # set; hydrology prod does not set it, so guarantee the platform-context
        # Link ourselves or Orion silently drops every nkz:* attr (spec §6.2).
        # TODO(phase1.5): once CONTEXT_URL is set in the hydrology deployment env
        # (gitops overlay), migrate to `await OrionClient(tenant).update_entity_attrs(id, attrs)` and drop this httpx.patch + manual Link.
        headers = inject_fiware_headers({}, auth.tenant_id, has_context_in_body=False)
        headers.setdefault(
            "Link",
            f'<{settings.context_url}>; rel="http://www.w3.org/ns/json-ld#context";'
            ' type="application/ld+json"',
        )
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
) -> dict:
    """Export a design in GPX, KML, or GeoJSON format.

    GPX/KML are returned as a JSON envelope ``{filename, mediaType, content}``
    rather than a raw XML body: the api-gateway auto-proxy
    (``safe_json_proxy_response``) 502s any non-JSON Content-Type, so an
    ``application/gpx+xml`` / KML response never reaches the browser. The
    frontend rebuilds the Blob from ``content`` + ``mediaType``. ``geojson``
    stays a GeoJSON Feature (already JSON, gateway-safe).
    """
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entity = orion.get_entity(design_id)
    except Exception:
        logger.exception("Failed to export design %s", design_id)
        raise HTTPException(status_code=404, detail="Design not found")

    geom = (entity.get("location", {}) or {}).get("value", {})
    if not geom:
        raise HTTPException(status_code=404, detail="Design has no geometry")

    name = nkz_attr(entity, "label") or "Hydrology Design"

    if format == "gpx":
        return {
            "filename": f"{name}.gpx",
            "mediaType": "application/gpx+xml",
            "content": geometry_to_gpx(geom, name),
        }
    elif format == "kml":
        return {
            "filename": f"{name}.kml",
            "mediaType": "application/vnd.google-earth.kml+xml",
            "content": geometry_to_kml(geom, name),
        }
    else:
        return {"type": "Feature", "geometry": geom, "properties": {"name": name}}
