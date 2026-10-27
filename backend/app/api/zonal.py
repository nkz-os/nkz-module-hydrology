"""Zonal TWI statistics for externally supplied zone geometries."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from nkz_platform_sdk import AuthContext, SyncOrionClient
from pydantic import BaseModel, Field

from app.middleware import require_auth
from app.services.design_generator import download_raster
from app.services.zone_stats import parcel_p80, read_raster, zone_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parcels", tags=["hydrology-zonal"])

MAX_ZONES = 20
_HYDRO_RECORD_PREFIX = "urn:ngsi-ld:AgriParcelRecord:hydrology-"


class ZoneIn(BaseModel):
    zoneId: str
    zoneVersion: Optional[str] = None
    geometry: dict[str, Any]


class ZonalStatsRequest(BaseModel):
    zones: list[ZoneIn] = Field(max_length=MAX_ZONES)


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
    hydro.sort(key=_record_date, reverse=True)
    return _get_attr(hydro[0], "demSource"), _get_attr(hydro[0], "dataFidelity")


@router.post("/{parcel_id}/zonal-stats")
def zonal_stats(
    parcel_id: str,
    req: ZonalStatsRequest,
    auth: AuthContext = require_auth(),
) -> dict:
    twi_bytes = download_raster(parcel_id, auth.tenant_id, "twi.tif")
    if twi_bytes is None:
        raise HTTPException(status_code=404, detail="TWI raster not found for parcel")
    try:
        twi, transform, crs = read_raster(twi_bytes)
        slope_b = download_raster(parcel_id, auth.tenant_id, "slope.tif")
        accum_b = download_raster(parcel_id, auth.tenant_id, "accum.tif")
        slope = read_raster(slope_b)[0] if slope_b else None
        accum = read_raster(accum_b)[0] if accum_b else None
        zones = zone_stats(
            twi, slope, accum, transform, crs,
            [z.model_dump() for z in req.zones], parcel_p80(twi),
        )
    except Exception as e:
        logger.warning("zonal-stats failed parcel=%s tenant=%s: %s", parcel_id, auth.tenant_id, e)
        raise HTTPException(status_code=422, detail="Could not compute zone statistics")
    dem_source, fidelity = _latest_record_meta(auth.tenant_id, parcel_id)
    return {
        "parcel_id": parcel_id,
        "demSource": dem_source,
        "dataFidelity": fidelity,
        "zones": zones,
    }
