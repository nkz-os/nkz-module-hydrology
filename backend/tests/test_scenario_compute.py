"""On-demand scenario comparison (Phase 1.2)."""
from unittest.mock import patch

from app.services import scenario_compute


def _record(**over):
    base = {
        "id": "urn:ngsi-ld:AgriParcelRecord:hydrology-t1-p1-1",
        "dateObserved": "2026-01-01T00:00:00Z",
        "nkz:parcelAreaHa": 10.0,
        "nkz:runoffMm": 30.0,
        "nkz:sedimentYieldTonnes": 5.0,
        "nkz:etoMm": 4.0,
        "nkz:precipitationMm": 40.0,
    }
    base.update(over)
    return base


def _designs(capacities):
    return [{"id": f"d{i}", "nkz:capacity": c} for i, c in enumerate(capacities)]


def test_compute_scenarios_no_data_when_no_record():
    with patch.object(scenario_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.return_value = []
        r = scenario_compute.compute_scenarios("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "no_data"


def test_compute_scenarios_baseline_when_no_designs():
    with patch.object(scenario_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.side_effect = [[_record()], []]
        r = scenario_compute.compute_scenarios("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "ok"
    assert r["baseline"]["water_captured_m3"] == 0
    # No designs -> intervention captures nothing.
    assert r["intervention"]["water_captured_m3"] == 0
    assert r["designsConsidered"] == 0


def test_compute_scenarios_captures_from_pond_designs():
    # area 10 ha, runoff 30 mm -> 3000 m³ total runoff.
    # two ponds (1000 + 500 m³) -> 1500 captured -> capt_frac 0.5.
    with patch.object(scenario_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.side_effect = [
            [_record()],
            _designs([1000.0, 500.0]),
        ]
        r = scenario_compute.compute_scenarios("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "ok"
    assert r["intervention"]["water_captured_m3"] == 1500.0
    assert r["designsConsidered"] == 2
    # Sediment retained = baseline 5 t * 0.5 = 2.5 t.
    assert abs(r["intervention"]["sediment_retained_t"] - 2.5) < 1e-6
    assert r["baseline"]["sediment_retained_t"] == 0
    assert {c["name"] for c in r["comparison"]} == {"baseline", "intervention"}
    assert r["capturedM3"] == 1500.0
    assert r["assumptions"]


def test_compute_scenarios_caps_capture_at_total_runoff():
    # Pond capacity (10 000) exceeds total runoff (3000) -> capt_frac capped 1.0.
    with patch.object(scenario_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.side_effect = [[_record()], _designs([10_000.0])]
        r = scenario_compute.compute_scenarios("t1", "urn:ngsi-ld:AgriParcel:p1")
    assert r["status"] == "ok"
    assert abs(r["intervention"]["sediment_retained_t"] - 5.0) < 1e-6  # all sediment
