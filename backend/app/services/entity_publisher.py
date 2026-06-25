"""NGSI-LD dict builders for hydrology outputs (pure functions, no Orion I/O).

Mirrors the canonical pattern of nkz-module-weather-map/app/records.py:
  - AgriParcelRecord: historized, one record per DEM pipeline run, FLAT scalar
    Properties (telemetry-worker drops dict/list when historizing to Timescale).
  - AgriParcelZone:   static, upsert in-place, one per TWI quintile zone.

These builders return dicts only. The caller persists them via the SDK's
OrionClient (see records_publish.py). Each module owns ONLY its own capability:
hydrology records carry hydrology attributes, never duplicating weather/soil
data from other modules (composition is the consumer's job — AGENTS §8).
"""

from __future__ import annotations

import re
from typing import Any

# Hydrology KPIs that may appear on the AgriParcelRecord (all flat scalars).
# metric_name -> AgriParcelRecord attribute name (nkz: prefix = custom attribute).
_RECORD_METRICS: dict[str, str] = {
    "twiMean": "nkz:twiMean",
    "twiMax": "nkz:twiMax",
    "streamLengthM": "nkz:streamLengthM",
    "watershedAreaHa": "nkz:watershedAreaHa",
    "slopeMean": "nkz:slopeMean",
    # Weather KPIs (from weather-map, Ronda 2.3)
    "etoMm": "nkz:etoMm",
    "precipitationMm": "nkz:precipitationMm",
    "temperatureAvg": "nkz:temperatureAvg",
    "temperatureMin": "nkz:temperatureMin",
    "soilMoisture": "nkz:soilMoisture",
}

_DEM_SOURCES = {"lidar", "pnoa", "ign", "copernicus", "synthetic"}

# Allowed nkz:dataFidelity values (Property on AgriParcelRecord, NOT an SDM type).
# Aligns with the cross-module dataFidelity contract (AGENTS §8) and crop-health.
_DATA_FIDELITY = {"ign_5m", "ign_25m", "degraded_flat", "unavailable"}


def _parcel_short(parcel_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", parcel_id.split(":")[-1]).strip("-")


def _ts_compact(observed_at: str) -> str:
    return re.sub(r"[^0-9]", "", observed_at)


def build_hydrology_record(
    *,
    tenant_id: str,
    parcel_id: str,
    geometry: dict[str, Any],
    observed_at: str,
    metrics: dict[str, float],
    dem_source: str,
    data_fidelity: str = "ign_25m",
) -> dict[str, Any]:
    """Build a historized AgriParcelRecord dict for one DEM pipeline run.

    Args:
        tenant_id: Request tenant (from gateway X-Tenant-ID).
        parcel_id: Full AgriParcel URN.
        geometry: Parcel polygon GeoJSON.
        observed_at: ISO-8601 timestamp of the run.
        metrics: Flat-scalar KPIs (subset of _RECORD_METRICS keys). Missing keys
            are omitted from the record (never emitted as null).
        dem_source: One of _DEM_SOURCES (coarse category: ign/copernicus/lidar/...).
        data_fidelity: One of _DATA_FIDELITY (fine-grained: ign_5m/ign_25m/
            degraded_flat/unavailable).

    Returns:
        NGSI-LD entity dict (no @context; the SDK adds it on persist).
    """
    if dem_source not in _DEM_SOURCES:
        raise ValueError(f"dem_source must be one of {_DEM_SOURCES}, got {dem_source!r}")
    if data_fidelity not in _DATA_FIDELITY:
        raise ValueError(f"data_fidelity must be one of {_DATA_FIDELITY}, got {data_fidelity!r}")

    entity: dict[str, Any] = {
        "id": (
            f"urn:ngsi-ld:AgriParcelRecord:hydrology-"
            f"{tenant_id}-{_parcel_short(parcel_id)}-{_ts_compact(observed_at)}"
        ),
        "type": "AgriParcelRecord",
        "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
        "location": {"type": "GeoProperty", "value": geometry},
        "dateObserved": {"type": "Property", "value": {"@type": "DateTime", "@value": observed_at}},
        "nkz:demSource": {"type": "Property", "value": dem_source, "observedAt": observed_at},
        "nkz:dataFidelity": {"type": "Property", "value": data_fidelity, "observedAt": observed_at},
    }
    for metric_name, value in metrics.items():
        attr = _RECORD_METRICS.get(metric_name)
        if attr is None or value is None or isinstance(value, (dict, list)):
            continue
        entity[attr] = {"type": "Property", "value": float(value), "observedAt": observed_at}
    return entity


def build_hydrology_zones(
    tenant_id: str,
    parcel_id: str,
    observed_at: str,
    zones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build static AgriParcelZone dicts (one per TWI quintile zone).

    Args:
        tenant_id: Request tenant.
        parcel_id: Full AgriParcel URN.
        observed_at: ISO-8601 timestamp.
        zones: List of zone dicts, each with keys: zone_id, geometry, twiMean,
            twiRange (str), areaHa, pixelCount.

    Returns:
        List of NGSI-LD AgriParcelZone dicts (empty if zones is empty).
    """
    parcel_short = _parcel_short(parcel_id)
    out: list[dict[str, Any]] = []
    for z in zones:
        zone_id = z.get("zone_id")
        if not zone_id:
            continue
        entity: dict[str, Any] = {
            "id": f"urn:ngsi-ld:AgriParcelZone:{tenant_id}:{parcel_short}:{zone_id}",
            "type": "AgriParcelZone",
            "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
            "location": {"type": "GeoProperty", "value": z.get("geometry", {})},
            "dateObserved": {"type": "Property", "value": {"@type": "DateTime", "@value": observed_at}},
            "nkz:zoneId": {"type": "Property", "value": zone_id},
        }
        for key, attr in (
            ("twiMean", "nkz:twiMean"),
            ("twiRange", "nkz:twiRange"),
            ("areaHa", "nkz:areaHa"),
            ("pixelCount", "nkz:pixelCount"),
        ):
            value = z.get(key)
            if value is None or isinstance(value, (dict, list)):
                continue
            entity[attr] = {"type": "Property", "value": value}
        out.append(entity)
    return out
