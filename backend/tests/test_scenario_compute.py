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


def _run(record, designs=()):
    with patch.object(scenario_compute, "SyncOrionClient") as M:
        M.return_value.query_entities.side_effect = [[record], list(designs)]
        return scenario_compute.compute_scenarios("t1", "urn:ngsi-ld:AgriParcel:p1")


def test_storm_scenario_uses_design_runoff():
    rec = _record(**{"nkz:calculationMode": "storm", "nkz:designRainStatus": "ok",
                     "nkz:returnPeriodYears": 25, "nkz:runoffMm": 20.0})
    r = _run(rec, _designs([1000.0]))
    assert r["status"] == "ok"
    assert r["mode"] == "storm"
    assert r["returnPeriodYears"] == 25
    assert isinstance(r["returnPeriodYears"], int)
    # 20 mm * 10 ha = 2000 m3 reference; 1000 captured.
    assert r["intervention"]["water_captured_m3"] == 1000.0
    assert abs(r["intervention"]["sediment_retained_t"] - 2.5) < 1e-6


def test_retention_scenario_reports_m3_and_days():
    rec = _record(**{"nkz:calculationMode": "retention", "nkz:designRainStatus": "ok",
                     "nkz:retentionExtraStoredM3": 800.0, "nkz:retentionExtraSummerDays": 12,
                     "nkz:retentionBaselineSummerDays": 30,
                     "nkz:retentionDryExtraStoredM3": 500.0,
                     "nkz:retentionDryExtraSummerDays": 7,
                     "nkz:retentionDryBaselineSummerDays": 20})
    r = _run(rec)
    assert r["status"] == "ok"
    assert r["mode"] == "retention"
    assert r["returnPeriodYears"] is None
    assert r["retention"]["median"] == {
        "extraStoredM3": 800.0, "extraSummerDays": 12.0, "baselineSummerDays": 30.0}
    assert r["retention"]["dry"] == {
        "extraStoredM3": 500.0, "extraSummerDays": 7.0, "baselineSummerDays": 20.0}


def test_retention_missing_figures_is_not_available():
    r = _run(_record(**{"nkz:calculationMode": "retention", "nkz:designRainStatus": "ok"}))
    assert r["status"] == "not_available"
    assert r["reason"]


def test_unknown_mode_is_not_available():
    r = _run(_record(**{"nkz:calculationMode": "bogus"}))
    assert r["status"] == "not_available"
    assert "bogus" in r["reason"]


def test_design_rain_not_available_is_not_zeros():
    rec = _record(**{"nkz:calculationMode": "storm", "nkz:designRainStatus": "not_available",
                     "nkz:designRainReason": "short_history"})
    r = _run(rec)
    assert r["status"] == "not_available"
    assert r["reason"] == "short_history"
    assert r["mode"] == "storm"
    assert "baseline" not in r


def test_record_without_mode_uses_legacy_path():
    r = _run(_record())
    assert r["status"] == "ok"
    assert r["mode"] is None
