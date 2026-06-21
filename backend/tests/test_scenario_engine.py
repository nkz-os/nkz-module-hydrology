"""Tests for scenario engine — baseline, intervention, comparison."""

import pytest

from app.services.scenario_engine import (
    ScenarioKPI,
    simulate_baseline,
    simulate_intervention,
    compare_scenarios,
)


# ---------------------------------------------------------------------------
# ScenarioKPI
# ---------------------------------------------------------------------------

class TestScenarioKPI:
    """Verify ScenarioKPI dataclass defaults and construction."""

    def test_defaults_are_zero(self):
        kpi = ScenarioKPI()
        assert kpi.water_captured_m3 == 0
        assert kpi.runoff_avoided_m3 == 0
        assert kpi.sediment_retained_t == 0
        assert kpi.earthwork_m3 == 0
        assert kpi.investment_eur == 0
        assert kpi.water_autonomy_pct == 0
        assert kpi.reliability_pct == 0

    def test_constructed_with_values(self):
        kpi = ScenarioKPI(
            water_captured_m3=5000,
            runoff_avoided_m3=4500,
            sediment_retained_t=30,
            earthwork_m3=1200,
            investment_eur=9600,
            water_autonomy_pct=62.5,
            reliability_pct=85,
        )
        assert kpi.water_captured_m3 == 5000
        assert kpi.runoff_avoided_m3 == 4500
        assert kpi.sediment_retained_t == 30
        assert kpi.earthwork_m3 == 1200
        assert kpi.investment_eur == 9600
        assert kpi.water_autonomy_pct == 62.5
        assert kpi.reliability_pct == 85


# ---------------------------------------------------------------------------
# simulate_baseline
# ---------------------------------------------------------------------------

class TestSimulateBaseline:
    """Baseline always returns zero capture and retention."""

    def test_baseline_returns_zero_capture(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        assert bl.water_captured_m3 == 0
        assert bl.runoff_avoided_m3 == 0
        assert bl.sediment_retained_t == 0

    def test_baseline_ignores_flux_values(self):
        """Input fluxes do not affect baseline KPI output."""
        bl = simulate_baseline(0, 0, 0, 0)
        assert bl.water_captured_m3 == 0
        assert bl.runoff_avoided_m3 == 0
        assert bl.sediment_retained_t == 0

    def test_baseline_returns_defaults_for_unspecified_fields(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        assert bl.earthwork_m3 == 0
        assert bl.investment_eur == 0
        assert bl.water_autonomy_pct == 0
        assert bl.reliability_pct == 0


# ---------------------------------------------------------------------------
# simulate_intervention
# ---------------------------------------------------------------------------

class TestSimulateIntervention:
    """Verify intervention KPI computation."""

    def test_capture_and_avoided_runoff_equal_input(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        assert iv.water_captured_m3 == 6000
        assert iv.runoff_avoided_m3 == 6000

    def test_sediment_retained(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        assert iv.sediment_retained_t == 30

    def test_investment_from_earthwork_default_cost(self):
        """Default cost_per_m3 = 8.0 → 1200 * 8 = 9600."""
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        assert iv.investment_eur == 9600

    def test_investment_with_custom_cost(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200, cost_per_m3=12)
        assert iv.investment_eur == 14400

    def test_water_autonomy_exact(self):
        """6000 / 8000 * 100 = 75 %."""
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=8000)
        assert iv.water_autonomy_pct == 75.0

    def test_water_autonomy_capped_at_100(self):
        """Capture > demand → 100 %."""
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 10000, 30, 1200, irrigation_demand_m3=5000)
        assert iv.water_autonomy_pct == 100.0

    def test_water_autonomy_with_zero_demand(self):
        """Zero demand → division by zero avoided, result 0."""
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=0)
        assert iv.water_autonomy_pct == 0.0

    def test_reliability_carried_from_baseline(self):
        bl = ScenarioKPI(reliability_pct=72)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        assert iv.reliability_pct == 72

    def test_earthwork_stored(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 2500)
        assert iv.earthwork_m3 == 2500


# ---------------------------------------------------------------------------
# compare_scenarios
# ---------------------------------------------------------------------------

class TestCompareScenarios:
    """Verify the comparison table output."""

    def test_returns_list_of_dicts(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        result = compare_scenarios({"Baseline": bl, "Intervention": iv})
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(row, dict) for row in result)

    def test_each_row_has_name_and_all_kpi_fields(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        result = compare_scenarios({"Baseline": bl})
        row = result[0]
        assert "name" in row
        assert "water_captured_m3" in row
        assert "runoff_avoided_m3" in row
        assert "sediment_retained_t" in row
        assert "earthwork_m3" in row
        assert "investment_eur" in row
        assert "water_autonomy_pct" in row
        assert "reliability_pct" in row

    def test_values_match_kpi(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=8000)
        result = compare_scenarios({"Intervention": iv})
        row = result[0]
        assert row["water_captured_m3"] == 6000
        assert row["runoff_avoided_m3"] == 6000
        assert row["sediment_retained_t"] == 30
        assert row["earthwork_m3"] == 1200
        assert row["investment_eur"] == 9600
        assert row["water_autonomy_pct"] == 75.0

    def test_sorted_by_name(self):
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200)
        result = compare_scenarios({"Z": bl, "A": iv})
        assert result[0]["name"] == "A"
        assert result[1]["name"] == "Z"

    def test_empty_scenarios_returns_empty_list(self):
        result = compare_scenarios({})
        assert result == []

    def test_baseline_vs_intervention_hand_calculation(self):
        """Spot-check against known values."""
        bl = simulate_baseline(10000, 50, 2000, 5000)
        iv = simulate_intervention(bl, 6000, 30, 1200, irrigation_demand_m3=8000)
        result = compare_scenarios({"Baseline": bl, "Intervention": iv})

        baseline_row = next(r for r in result if r["name"] == "Baseline")
        assert baseline_row["water_captured_m3"] == 0
        assert baseline_row["investment_eur"] == 0
        assert baseline_row["water_autonomy_pct"] == 0

        intervention_row = next(r for r in result if r["name"] == "Intervention")
        assert intervention_row["water_captured_m3"] == 6000
        assert intervention_row["runoff_avoided_m3"] == 6000
        assert intervention_row["sediment_retained_t"] == 30
        assert intervention_row["earthwork_m3"] == 1200
        assert intervention_row["investment_eur"] == 9600
        assert intervention_row["water_autonomy_pct"] == 75.0
