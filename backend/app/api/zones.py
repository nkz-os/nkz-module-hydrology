"""Hydrology zone endpoints — zonal KPIs and PMTiles URL."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from nkz_platform_sdk import SyncOrionClient, AuthContext

from app.middleware import require_auth

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


def _get_attr(entity: dict, name: str):
    """Read a possibly nkz:-prefixed keyValues attribute, unwrapping a normalized
    {type, value} dict if Orion did not compact to a scalar."""
    for key in (f"nkz:{name}", name):
        if key in entity:
            v = entity[key]
            if isinstance(v, dict):
                v = v.get("value", v.get("@value"))
            return v
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
            zone: dict = {"id": e.get("id", ""), "type": e.get("type", "")}
            for key in (
                "nkz:zoneId",
                "nkz:twiMean",
                "nkz:twiRange",
                "nkz:areaHa",
                "nkz:runoffMm",
                "nkz:sedimentYieldTonnes",
                "nkz:soilSaturationPct",
                "nkz:pondViability",
                "nkz:keylineGrade",
            ):
                val = e.get(key)
                if isinstance(val, dict):
                    zone[key.replace("nkz:", "")] = val.get("value")
                else:
                    zone[key.replace("nkz:", "")] = val
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
        entities = orion.query_entities(
            type="AgriParcelRecord",
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
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


@router.get("/{parcel_id}/pmtiles-url")
def get_pmtiles_url(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Get a presigned MinIO GET URL for the TWI PMTiles of this parcel.

    The bucket is private; returns ``url: null`` + ``status: not_generated`` when
    the object does not exist yet, never a guessed (403-ing) URL.
    """
    from app.services.tile_service import twi_pmtiles_key, get_public_url, pmtiles_exists
    key = twi_pmtiles_key(parcel_id, auth.tenant_id)
    if not pmtiles_exists(parcel_id, auth.tenant_id, "twi"):
        return {"url": None, "key": key, "status": "not_generated"}
    return {"url": get_public_url(key), "key": key}
