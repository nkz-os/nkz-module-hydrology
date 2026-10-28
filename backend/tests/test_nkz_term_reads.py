"""nkz: terms come back from the broker prefixed, compacted by the @context, or as
their full IRI; every reader must take all three, and only hydrology zones count."""
from unittest.mock import patch

from nkz_platform_sdk import AuthContext

from app.services.hydro_record import nkz_attr

NS = "https://nkz-os.org/ns/"
PARCEL = "urn:ngsi-ld:AgriParcel:p-1"
AUTH = AuthContext(tenant_id="tenant-a", user_id="u-1", roles=())


def test_nkz_attr_reads_every_form_and_unwraps():
    assert nkz_attr({"nkz:twiMean": 1.5}, "twiMean") == 1.5
    assert nkz_attr({"twiMean": {"type": "Property", "value": 2.5}}, "twiMean") == 2.5
    assert nkz_attr({NS + "twiMean": {"type": "Property", "value": 3.5}}, "twiMean") == 3.5
    assert nkz_attr({NS + "twiRange": {"@value": "1-2"}}, "twiRange") == "1-2"
    assert nkz_attr({}, "twiMean") is None


def _zone(zone_id, **attrs):
    return {"id": f"urn:ngsi-ld:AgriParcelZone:tenant-a:p-1:{zone_id}", "type": "AgriParcelZone", **attrs}


def test_zones_endpoint_returns_only_hydrology_zones_with_their_values():
    from app.api import zones

    entities = [
        _zone("twi-high",
              areaHa={"type": "Property", "value": 4.2},
              **{NS + "zoneId": {"type": "Property", "value": "twi-high"},
                 NS + "zoneType": {"type": "Property", "value": "hydrology"},
                 NS + "twiMean": {"type": "Property", "value": 9.1},
                 NS + "runoffMm": {"type": "Property", "value": 12.0}},
              location={"type": "GeoProperty", "value": {"type": "Polygon", "coordinates": []}}),
        # Zone written before the zoneType tag existed: recognised by its id.
        _zone("twi-low", **{NS + "twiMean": {"type": "Property", "value": 4.0}}),
        # Another module's management zone on the same parcel.
        _zone("zezwd8dp-e11-S", **{NS + "zoneType": {"type": "Property", "value": "management"}}),
        _zone("zezwd89f-e10-NE"),
    ]
    with patch.object(zones, "SyncOrionClient") as orion:
        orion.return_value.query_entities.return_value = entities
        out = zones.get_parcel_zones(PARCEL, auth=AUTH)
    assert [z["id"].rsplit(":", 1)[-1] for z in out] == ["twi-high", "twi-low"]
    assert out[0]["twiMean"] == 9.1 and out[0]["areaHa"] == 4.2 and out[0]["runoffMm"] == 12.0
    assert out[0]["zoneId"] == "twi-high" and out[0]["geometry"]["type"] == "Polygon"


def test_scenarios_read_full_iri_record_terms():
    from app.services import scenario_compute

    record = {"id": "urn:ngsi-ld:AgriParcelRecord:hydrology-x",
              NS + "parcelAreaHa": 10.0, NS + "runoffMm": 20.0, NS + "precipitationMm": 50.0,
              NS + "etoMm": 3.0, NS + "sedimentYieldTonnes": 1.0}
    real_baseline = scenario_compute.simulate_baseline
    seen = []

    def spy(*args):
        seen.append(args)
        return real_baseline(*args)

    with patch.object(scenario_compute, "SyncOrionClient") as orion, \
            patch.object(scenario_compute, "latest_hydro_record", return_value=record), \
            patch.object(scenario_compute, "simulate_baseline", side_effect=spy):
        orion.return_value.query_entities.return_value = []
        out = scenario_compute.compute_scenarios("tenant-a", PARCEL)
    assert out["status"] == "ok"
    # 20 mm of runoff, 1 t of sediment, 3 mm ET and 50 mm rain over 10 ha.
    assert seen == [(2000.0, 1.0, 300.0, 5000.0)]


def test_alerts_read_full_iri_record_terms():
    from app.services import alerts_compute

    record = {NS + "soilSaturationPct": 95.0, NS + "precipitationMm": 80.0, NS + "slopeMean": 20.0}
    seen = {}

    def fake_eval(**kw):
        seen.update(kw)
        return []

    with patch.object(alerts_compute, "SyncOrionClient"), \
            patch.object(alerts_compute, "latest_hydro_record", return_value=record), \
            patch.object(alerts_compute, "evaluate_alerts", side_effect=fake_eval):
        alerts_compute.compute_alerts("tenant-a", PARCEL)
    assert seen["bucket_state"] == {"saturation_pct": 95.0}
    assert seen["forecast_precip"] == 80.0
