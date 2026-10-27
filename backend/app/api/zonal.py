"""Zonal TWI statistics for externally supplied zone geometries."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from nkz_platform_sdk import AuthContext, SyncOrionClient
from pydantic import BaseModel, Field
from shapely.geometry import shape

from app.config import get_settings
from app.middleware import require_auth
from app.services.design_generator import _raster_key
from app.services.s3 import get_s3_client
from app.services.zone_stats import parcel_p80, read_raster, zone_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parcels", tags=["hydrology-zonal"])

MAX_ZONES = 20
_HYDRO_RECORD_PREFIX = "urn:ngsi-ld:AgriParcelRecord:hydrology-"
_SAFE_ID = re.compile(r"^[A-Za-z0-9:_.-]+$")
_NOT_FOUND_CODES = {"NoSuchKey", "404", "NotFound"}


class ZoneIn(BaseModel):
    zoneId: str
    zoneVersion: Optional[str] = None
    geometry: dict[str, Any]


class ZonalStatsRequest(BaseModel):
    zones: list[ZoneIn] = Field(max_length=MAX_ZONES)


def _fetch_raster(parcel_id: str, tenant_id: str, name: str) -> Optional[bytes]:
    """Object bytes, None only if the object does not exist; storage faults -> 502."""
    key = _raster_key(parcel_id, tenant_id, name)
    try:
        resp = get_s3_client().get_object(Bucket=get_settings().minio_bucket, Key=key)
        return resp["Body"].read()
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        if code in _NOT_FOUND_CODES:
            return None
        logger.error("zonal-stats: storage error key=%s code=%s", key, code)
        raise HTTPException(status_code=502, detail="Raster storage unavailable")
    except Exception as e:
        logger.error("zonal-stats: storage failure key=%s: %s", key, e)
        raise HTTPException(status_code=502, detail="Raster storage unavailable")


def _validate_zones(zones: list[ZoneIn]) -> None:
    for z in zones:
        g = z.geometry
        reason = None
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            reason = "geometry must be Polygon or MultiPolygon"
        else:
            try:
                sg = shape(g)
                if sg.is_empty:
                    reason = "geometry is empty"
            except Exception:
                reason = "geometry is not parseable"
        if reason:
            raise HTTPException(status_code=422, detail=f"zone {z.zoneId}: {reason}")


def _latest_record_meta(tenant_id: str, parcel_id: str) -> tuple[Optional[str], Optional[str]]:
    """(demSource, dataFidelity) of the latest hydrology record, else (None, None)."""
    try:
        entities = SyncOrionClient(tenant_id).query_entities(
            type="AgriParcelRecord",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");nkz:demSource',
            options="keyValues",
            limit=100,
        )
    except Exception as e:  # metadata is best-effort; stats do not depend on it
        logger.warning("zonal-stats: record lookup failed: %s", e)
        return None, None
    from app.api.zones import _get_attr, _record_date

    hydro = [e for e in (entities or []) if str(e.get("id", "")).startswith(_HYDRO_RECORD_PREFIX)]
    if not hydro:
        return None, None
    latest = max(hydro, key=_record_date)
    return _get_attr(latest, "demSource"), _get_attr(latest, "dataFidelity")


@router.post("/{parcel_id}/zonal-stats")
def zonal_stats(
    parcel_id: str,
    req: ZonalStatsRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    if not _SAFE_ID.match(parcel_id):
        raise HTTPException(status_code=422, detail="invalid parcel id")
    _validate_zones(req.zones)

    twi_bytes = _fetch_raster(parcel_id, auth.tenant_id, "twi.tif")
    if twi_bytes is None:
        raise HTTPException(status_code=404, detail="TWI raster not found for parcel")
    slope_b = _fetch_raster(parcel_id, auth.tenant_id, "slope.tif")
    accum_b = _fetch_raster(parcel_id, auth.tenant_id, "accum.tif")
    try:
        twi, transform, crs = read_raster(twi_bytes)
        if crs is None:
            raise ValueError("TWI raster has no CRS")
        slope = read_raster(slope_b)[0] if slope_b else None
        accum = read_raster(accum_b)[0] if accum_b else None
        p80 = parcel_p80(twi)
    except Exception as e:
        logger.error("zonal-stats: unreadable raster parcel=%s tenant=%s: %s", parcel_id, auth.tenant_id, e)
        raise HTTPException(status_code=500, detail="Stored raster is unusable")

    zones = zone_stats(twi, slope, accum, transform, crs, [z.model_dump() for z in req.zones], p80)
    dem_source, fidelity = _latest_record_meta(auth.tenant_id, parcel_id)
    return {
        "parcel_id": parcel_id,
        "demSource": dem_source,
        "dataFidelity": fidelity,
        "zones": zones,
    }
