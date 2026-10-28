"""Hydrology zone endpoints — zonal KPIs and PMTiles URL."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from nkz_platform_sdk import SyncOrionClient, AuthContext

from app.middleware import require_auth
from app.services.hydro_record import nkz_attr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parcels", tags=["hydrology-zones"])

# Only records this module published carry this id prefix. Other modules
# (weather-map) publish AgriParcelRecord too under the same type — the prefix
# filter is mandatory or their records would surface here.
_HYDRO_RECORD_PREFIX = "urn:ngsi-ld:AgriParcelRecord:hydrology-"

# KPI attribute names surfaced in the summary (nkz: prefix stripped). Source of
# truth is entity_publisher._RECORD_METRICS; soilSource/vegetationSource are
# reported at top level, watershedAreaHa is not surfaced here.
_SUMMARY_KPIS = (
    "twiMean", "twiMax", "slopeMean", "streamLengthM",
    "runoffMm", "peakFlowM3s", "sedimentYieldTonnes", "soilSaturationPct",
    "keylineGrade", "pondViability",
    "etoMm", "precipitationMm", "temperatureAvg", "temperatureMin", "soilMoisture",
)


def _record_date(entity: dict) -> str:
    """Tolerant dateObserved parse: keyValues may return a plain ISO string OR a
    {"@type","@value"} dict (or the normalized {"value": ...})."""
    d = entity.get("dateObserved")
    if isinstance(d, dict):
        v = d.get("@value")
        if not isinstance(v, str):
            v = d.get("value")
        return str(v or "")
    return str(d or "")


_get_attr = nkz_attr

_ZONE_KPIS = (
    "zoneId", "twiMean", "twiRange", "areaHa", "runoffMm", "peakFlowM3s",
    "sedimentYieldTonnes", "soilSaturationPct", "pondViability", "keylineGrade",
)


def _is_hydrology_zone(entity: dict) -> bool:
    """Zones this module wrote. Other modules (weather-map management zones) publish
    AgriParcelZone on the same parcel; zones from before the zoneType tag are
    recognised by their twi- id suffix."""
    zone_type = nkz_attr(entity, "zoneType")
    if zone_type is not None:
        return zone_type == "hydrology"
    return str(entity.get("id", "")).rsplit(":", 1)[-1].startswith("twi-")
    return None


@router.get("/{parcel_id}/zones")
def get_parcel_zones(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> list[dict]:
    """Get AgriParcelZone entities with zonal KPIs for a parcel."""
    try:
        orion = SyncOrionClient(auth.tenant_id)
        entities = orion.query_entities(
            type="AgriParcelZone",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
        )
        zones = []
        for e in entities:
            if not _is_hydrology_zone(e):
                continue
            zone: dict = {"id": e.get("id", ""), "type": e.get("type", "")}
            for name in _ZONE_KPIS:
                zone[name] = nkz_attr(e, name)
            # Geometry (GeoProperty) so the viewer can render zone polygons.
            loc = e.get("location")
            if isinstance(loc, dict):
                gval = loc.get("value")
                if isinstance(gval, dict) and gval.get("type"):
                    zone["geometry"] = gval
            zones.append(zone)
        return zones
    except Exception as e:
        logger.warning("Failed to get parcel zones: %s", e)
        return []


@router.get("/{parcel_id}/summary")
def get_parcel_summary(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Latest hydrology AgriParcelRecord for a parcel, as flat summary KPIs.

    Returns ``{status: "no_data"}`` when this module has published no record for
    the parcel yet (foreign-module records are filtered out by id prefix).
    """
    try:
        orion = SyncOrionClient(auth.tenant_id)
        # nkz:demSource existence term: hydrology records always stamp it
        # (entity_publisher.build_hydrology_record) — server-side discrimination
        # so foreign AgriParcelRecord (weather-map) can't crowd hydrology out of
        # the limit=100 page. The id-prefix post-filter stays as defense-in-depth.
        entities = orion.query_entities(
            type="AgriParcelRecord",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");nkz:demSource',
            options="keyValues",
            limit=100,
        )
    except Exception as e:
        logger.warning("Failed to get parcel summary: %s", e)
        return {"status": "no_data"}

    hydro = [
        e for e in (entities or [])
        if str(e.get("id", "")).startswith(_HYDRO_RECORD_PREFIX)
    ]
    if not hydro:
        return {"status": "no_data"}

    hydro.sort(key=_record_date, reverse=True)
    latest = hydro[0]

    kpis: dict = {}
    for name in _SUMMARY_KPIS:
        val = _get_attr(latest, name)
        if val is not None:
            kpis[name] = val

    return {
        "observedAt": _record_date(latest) or None,
        "dataFidelity": _get_attr(latest, "dataFidelity"),
        "demSource": _get_attr(latest, "demSource"),
        "soilSource": _get_attr(latest, "soilSource"),
        "vegetationSource": _get_attr(latest, "vegetationSource"),
        "kpis": kpis,
    }



