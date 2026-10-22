"""Tests for the hydrology NGSI-LD dict builders (pure functions, no Orion)."""
import re

import pytest

from app.services.entity_publisher import build_hydrology_record, build_hydrology_zones


TENANT = "tenant-a"
PARCEL = "urn:ngsi-ld:AgriParcel:parcel-123"
POLY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
OBSERVED = "2026-06-24T10:00:00Z"


def _parcel_short(pid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", pid.split(":")[-1]).strip("-")


def test_record_is_agri_parcel_record_type():
    rec = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
        observed_at=OBSERVED, metrics={"twiMean": 8.5, "twiMax": 19.1, "streamLengthM": 1240.0,
                                         "watershedAreaHa": 12.3, "slopeMean": 6.2},
        dem_source="ign",
    )
    assert rec["type"] == "AgriParcelRecord"
    assert rec["hasAgriParcel"] == {"type": "Relationship", "object": PARCEL}
    assert rec["location"] == {"type": "GeoProperty", "value": POLY}
    assert rec["dateObserved"] == {"type": "Property", "value": {"@type": "DateTime", "@value": OBSERVED}}


def test_record_id_scheme_matches_weather_map_pattern():
    rec = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
        observed_at=OBSERVED, metrics={"twiMean": 1.0}, dem_source="synthetic",
    )
    ts_compact = re.sub(r"[^0-9]", "", OBSERVED)
    assert rec["id"] == f"urn:ngsi-ld:AgriParcelRecord:hydrology-{TENANT}-{_parcel_short(PARCEL)}-{ts_compact}"


def test_record_metrics_are_flat_scalars_with_observedat():
    rec = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
        observed_at=OBSERVED, metrics={"twiMean": 8.5, "twiMax": 19.1}, dem_source="ign",
    )
    for key in ("nkz:twiMean", "nkz:twiMax"):
        assert key in rec
        attr = rec[key]
        assert attr["type"] == "Property"
        assert isinstance(attr["value"], float)
        assert attr["observedAt"] == OBSERVED
        # telemetry-worker rule: no dict/list values
        assert not isinstance(attr["value"], (dict, list))


def test_record_demsource_is_scalar_string():
    rec = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
        observed_at=OBSERVED, metrics={}, dem_source="pnoa",
    )
    assert rec["nkz:demSource"] == {"type": "Property", "value": "pnoa", "observedAt": OBSERVED}


def test_record_omits_missing_metrics_not_null():
    rec = build_hydrology_record(
        tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
        observed_at=OBSERVED, metrics={"twiMean": 1.0}, dem_source="ign",
    )
    assert "nkz:twiMean" in rec
    assert "nkz:streamLengthM" not in rec  # omitted, not null


def test_record_rejects_unknown_dem_source():
    import pytest
    with pytest.raises(ValueError):
        build_hydrology_record(
            tenant_id=TENANT, parcel_id=PARCEL, geometry=POLY,
            observed_at=OBSERVED, metrics={"twiMean": 1.0}, dem_source="bogus",
        )


def test_zones_returns_list_of_agri_parcel_zone():
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[
            {"zone_id": "twi-very-low", "geometry": POLY, "twiMean": 2.1,
             "twiRange": "[0,4]", "areaHa": 2.5, "pixelCount": 250},
            {"zone_id": "twi-very-high", "geometry": POLY, "twiMean": 18.0,
             "twiRange": "[16,30]", "areaHa": 1.0, "pixelCount": 100},
        ],
    )
    assert len(zones) == 2
    assert all(z["type"] == "AgriParcelZone" for z in zones)
    assert all(z["hasAgriParcel"] == {"type": "Relationship", "object": PARCEL} for z in zones)


def test_zone_id_is_static_no_timestamp():
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-mid", "geometry": POLY, "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    z = zones[0]
    assert z["id"] == f"urn:ngsi-ld:AgriParcelZone:{TENANT}:{_parcel_short(PARCEL)}:twi-mid"


def test_zones_empty_input_returns_empty_list():
    assert build_hydrology_zones(TENANT, PARCEL, OBSERVED, zones=[]) == []


def test_zone_valid_geometry_includes_location():
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-mid", "geometry": POLY, "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    z = zones[0]
    assert z["location"] == {"type": "GeoProperty", "value": POLY}


def test_zone_empty_geometry_omits_location():
    """An empty geometry dict must NOT emit an invalid empty GeoProperty."""
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-mid", "geometry": {}, "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    assert "location" not in zones[0]


def test_zone_missing_geometry_omits_location():
    """A zone with no geometry key at all omits location."""
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-mid", "twiMean": 8.0,
                "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    assert "location" not in zones[0]


def test_zone_typeless_geometry_omits_location():
    """A geometry dict lacking a 'type' key is not a valid GeoJSON geometry."""
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-mid", "geometry": {"coordinates": [[0, 0]]},
                "twiMean": 8.0, "twiRange": "[6,10]", "areaHa": 3.0, "pixelCount": 300}],
    )
    assert "location" not in zones[0]


def test_zone_attrs_are_flat_scalars():
    zones = build_hydrology_zones(
        tenant_id=TENANT, parcel_id=PARCEL, observed_at=OBSERVED,
        zones=[{"zone_id": "twi-low", "geometry": POLY, "twiMean": 3.0,
                "twiRange": "[0,4]", "areaHa": 2.0, "pixelCount": 200}],
    )
    z = zones[0]
    for key in ("nkz:zoneId", "nkz:twiMean", "nkz:twiRange", "nkz:areaHa", "nkz:pixelCount"):
        assert key in z
        assert z[key]["type"] == "Property"
        assert not isinstance(z[key]["value"], (dict, list))


def test_record_includes_data_fidelity_property():
    rec = build_hydrology_record(
        tenant_id="t1",
        parcel_id="urn:ngsi-ld:AgriParcel:p1",
        geometry={"type": "Point", "coordinates": [-1.64, 42.82]},
        observed_at="2026-06-24T12:00:00Z",
        metrics={"twiMean": 6.5},
        dem_source="ign",
        data_fidelity="ign_25m",
    )
    assert rec["nkz:dataFidelity"] == {
        "type": "Property", "value": "ign_25m", "observedAt": "2026-06-24T12:00:00Z"
    }


def test_record_rejects_invalid_data_fidelity():
    with pytest.raises(ValueError):
        build_hydrology_record(
            tenant_id="t1",
            parcel_id="urn:ngsi-ld:AgriParcel:p1",
            geometry={"type": "Point", "coordinates": [0, 0]},
            observed_at="2026-06-24T12:00:00Z",
            metrics={},
            dem_source="ign",
            data_fidelity="bogus",
        )
