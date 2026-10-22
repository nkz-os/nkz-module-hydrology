"""On-demand hydrologic alerts (Phase 2A — reactive)."""
from unittest.mock import patch

from app.services import alerts_compute


def _record(**over):
    base = {
        "id": "urn:ngsi-ld:AgriParcelRecord:hydrology-t1-p1-1",
        "dateObserved": "2026-01-01T00:00:00Z",
        "nkz:soilSaturationPct": 85.0,
        "nkz:precipitationMm": 15.0,
        "nkz:slopeMean": 8.0,
    }
    base.update(over)
    return base


def test_no_data_when_no_record():
    with patch.object(alerts_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.return_value = []
        r = alerts_compute.compute_alerts("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "no_data"


def test_saturation_excess_critical_when_saturated_and_rain():
    # sat 85% (>80) + precip 15mm (>10) -> critical saturation-excess (Dunne).
    with patch.object(alerts_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.return_value = [_record()]
        r = alerts_compute.compute_alerts("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "ok"
    mechanisms = [a["mechanism"] for a in r["alerts"]]
    assert "saturationExcess" in mechanisms
    assert any(a["severity"] == "critical" for a in r["alerts"])


def test_no_alerts_when_calm():
    with patch.object(alerts_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.return_value = [
            _record(**{"nkz:soilSaturationPct": 40.0, "nkz:precipitationMm": 2.0})
        ]
        r = alerts_compute.compute_alerts("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "ok"
    assert r["alerts"] == []
    assert r["inputs"]["ndvi"] == 0.5  # default (not persisted)
