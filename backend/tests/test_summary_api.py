"""Tests for the parcel summary endpoint (surfaces the latest AgriParcelRecord)."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import FastAPI


def _hydro_record(ts: str, **attrs):
    e = {
        "id": f"urn:ngsi-ld:AgriParcelRecord:hydrology-t1-p1-{ts.replace('-', '').replace(':', '')}",
        "type": "AgriParcelRecord",
        "dateObserved": {"@type": "DateTime", "@value": ts},
    }
    e.update(attrs)
    return e


def _call(records):
    from app.api import zones
    with patch.object(zones, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = records
        return zones.get_parcel_summary(
            parcel_id="urn:ngsi-ld:AgriParcel:p1",
            auth=SimpleNamespace(tenant_id="t1"),
        )


def test_summary_picks_latest_hydrology_record():
    older = _hydro_record("2026-07-10T00:00:00Z", **{"nkz:twiMean": 5.0})
    newer = _hydro_record(
        "2026-07-16T00:00:00Z",
        **{
            "nkz:twiMean": 7.5,
            "nkz:runoffMm": 12.3,
            "nkz:demSource": "ign",
            "nkz:dataFidelity": "ign_5m",
            "nkz:soilSource": "orion",
            "nkz:vegetationSource": "default",
        },
    )
    result = _call([older, newer])
    assert result["observedAt"] == "2026-07-16T00:00:00Z"
    assert result["dataFidelity"] == "ign_5m"
    assert result["demSource"] == "ign"
    assert result["soilSource"] == "orion"
    assert result["vegetationSource"] == "default"
    assert result["kpis"]["twiMean"] == 7.5
    assert result["kpis"]["runoffMm"] == 12.3


def test_summary_ignores_other_modules_records():
    """weather-map publishes AgriParcelRecord too — id prefix filter is mandatory."""
    foreign = {
        "id": "urn:ngsi-ld:AgriParcelRecord:weather-t1-p1-20260716",
        "type": "AgriParcelRecord",
        "dateObserved": {"@type": "DateTime", "@value": "2026-07-16T00:00:00Z"},
        "nkz:twiMean": 99.0,
    }
    hydro = _hydro_record("2026-07-11T00:00:00Z", **{"nkz:twiMean": 4.2})
    result = _call([foreign, hydro])
    # Foreign record is newer but must not be selected.
    assert result["observedAt"] == "2026-07-11T00:00:00Z"
    assert result["kpis"]["twiMean"] == 4.2


def test_summary_no_data_when_empty():
    assert _call([]) == {"status": "no_data"}


def test_summary_no_data_when_only_foreign():
    foreign = {
        "id": "urn:ngsi-ld:AgriParcelRecord:weather-t1-p1-20260716",
        "type": "AgriParcelRecord",
        "dateObserved": {"@type": "DateTime", "@value": "2026-07-16T00:00:00Z"},
    }
    assert _call([foreign]) == {"status": "no_data"}


def test_summary_omits_missing_kpis():
    rec = _hydro_record("2026-07-16T00:00:00Z", **{"nkz:twiMean": 7.5})
    result = _call([rec])
    assert result["kpis"] == {"twiMean": 7.5}
    assert "runoffMm" not in result["kpis"]


def test_summary_tolerates_plain_string_date():
    """keyValues may return dateObserved as a plain ISO string, not a dict."""
    rec = _hydro_record("2026-07-16T00:00:00Z", **{"nkz:twiMean": 7.5})
    rec["dateObserved"] = "2026-07-16T00:00:00Z"
    result = _call([rec])
    assert result["observedAt"] == "2026-07-16T00:00:00Z"


def test_summary_query_uses_or_pipe_and_keyvalues():
    from app.api import zones
    pid = "urn:ngsi-ld:AgriParcel:p1"
    with patch.object(zones, "SyncOrionClient") as MockOrion:
        MockOrion.return_value.query_entities.return_value = []
        zones.get_parcel_summary(parcel_id=pid, auth=SimpleNamespace(tenant_id="t1"))
    _, kwargs = MockOrion.return_value.query_entities.call_args
    assert kwargs["q"] == f'(hasAgriParcel=="{pid}"|refAgriParcel=="{pid}")'
    assert kwargs["options"] == "keyValues"


def test_summary_requires_auth():
    from app.api.zones import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/parcels/p1/summary")
    assert resp.status_code == 401
