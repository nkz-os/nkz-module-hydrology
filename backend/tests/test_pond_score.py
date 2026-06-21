"""Tests for pondScore multi-objective siting score."""

import pytest

from app.services.pond_score import pond_score


# ---------------------------------------------------------------------------
# pond_score
# ---------------------------------------------------------------------------

class TestPondScore:
    """Verify the pondScore formula, viability, and lining logic."""

    def test_zero_earthwork_returns_not_viable(self):
        """No excavation → score 0, not viable."""
        result = pond_score(5000, 0, 75, 5, "clay")
        assert result["pondScore"] == 0.0
        assert result["isViable"] is False

    def test_zero_yield_returns_not_viable(self):
        """No catchment yield → score 0, not viable."""
        result = pond_score(0, 800, 75, 5, "clay")
        assert result["pondScore"] == 0.0
        assert result["isViable"] is False

    def test_both_zero_returns_not_viable(self):
        result = pond_score(0, 0, 75, 5, "clay")
        assert result["pondScore"] == 0.0
        assert result["isViable"] is False

    def test_score_increases_with_yield(self):
        """Higher yield → higher pondScore, all else equal."""
        low = pond_score(1000, 800, 50, 5, "clay")
        high = pond_score(10000, 800, 50, 5, "clay")
        assert high["pondScore"] > low["pondScore"]

    def test_score_decreases_with_earthwork(self):
        """More earthwork → lower score (higher cost)."""
        low = pond_score(5000, 200, 50, 5, "clay")
        high = pond_score(5000, 2000, 50, 5, "clay")
        assert low["pondScore"] > high["pondScore"]

    def test_score_increases_with_reliability(self):
        """More reliable → higher score."""
        low = pond_score(5000, 800, 30, 5, "clay")
        high = pond_score(5000, 800, 90, 5, "clay")
        assert high["pondScore"] > low["pondScore"]

    def test_viability_threshold(self):
        """Score > 0.4 → viable; score ≤ 0.4 → not viable."""
        viable = pond_score(5000, 800, 75, 5, "clay")
        assert viable["isViable"] is True
        assert viable["pondScore"] > 0.4

        not_viable = pond_score(100, 2000, 10, 5, "sand")
        assert not_viable["isViable"] is False
        assert not_viable["pondScore"] <= 0.4

    def test_clay_is_highest_soil_score(self):
        """Clay provides the best soil suitability → highest soil factor."""
        clay = pond_score(5000, 800, 50, 5, "clay")
        sand = pond_score(5000, 800, 50, 5, "sand")
        assert clay["factors"]["soil"] > sand["factors"]["soil"]

    def test_requires_lining_for_sand(self):
        """Sand texture → requiresLining = True."""
        result = pond_score(5000, 800, 50, 5, "sand")
        assert result["requiresLining"] is True

    def test_requires_lining_for_sandy_loam(self):
        """Sandy loam texture → requiresLining = True."""
        result = pond_score(5000, 800, 50, 5, "sandy_loam")
        assert result["requiresLining"] is True

    def test_no_lining_for_clay(self):
        """Clay texture → requiresLining = False (unless Ksat high)."""
        result = pond_score(5000, 800, 50, 5, "clay")
        assert result["requiresLining"] is False

    def test_no_lining_for_clay_loam(self):
        """Clay loam → requiresLining = False."""
        result = pond_score(5000, 800, 50, 5, "clay_loam")
        assert result["requiresLining"] is False

    def test_high_ksat_triggers_lining_regardless_of_texture(self):
        """Ksat > 10 mm/h → lining required even for clay."""
        result = pond_score(5000, 800, 50, 15, "clay")
        assert result["requiresLining"] is True

    def test_high_efficiency_saturates_at_0_4(self):
        """eff >= 100 → efficiency score saturates at 0.4."""
        result = pond_score(100000, 800, 50, 5, "clay")
        assert result["factors"]["efficiency"] == pytest.approx(0.4)
        assert result["pondScore"] <= 1.0

    def test_pond_score_never_exceeds_1(self):
        """Even with perfect inputs, pondScore ≤ 1."""
        result = pond_score(1e9, 1, 100, 1, "clay")
        assert result["pondScore"] <= 1.0

    def test_returns_expected_keys(self):
        """Result dict has all expected keys."""
        result = pond_score(5000, 800, 75, 5, "loam")
        assert set(result.keys()) == {
            "pondScore", "isViable", "requiresLining", "factors",
        }
        assert set(result["factors"].keys()) == {
            "efficiency", "reliability", "soil", "cost",
        }

    def test_default_texture_is_loam(self):
        """Default texture 'loam' is accepted."""
        result = pond_score(5000, 800, 75, 5)
        assert result["isViable"] is True
        assert result["requiresLining"] is False

    def test_unknown_texture_uses_default_score(self):
        """Unrecognised texture is handled gracefully (0.5 * 0.2 = 0.1)."""
        result = pond_score(5000, 800, 50, 5, "gravel")
        assert result["factors"]["soil"] == pytest.approx(0.1)

    def test_reliability_at_boundaries(self):
        """0 % reliability → 0 contribution; 100 % → 0.3."""
        zero_rel = pond_score(5000, 800, 0, 5, "clay")
        assert zero_rel["factors"]["reliability"] == 0.0

        full_rel = pond_score(5000, 800, 100, 5, "clay")
        assert full_rel["factors"]["reliability"] == pytest.approx(0.3)

    def test_low_earthwork_cost_score_limited(self):
        """Very small earthwork → cost factor capped at 0.1."""
        tiny = pond_score(5000, 50, 50, 5, "clay")
        assert tiny["factors"]["cost"] == pytest.approx(0.1)

    def test_known_case_vs_hand_calculation(self):
        """Spot-check against a known manual computation."""
        eff = min(0.4, 5000 / 800 / 100 * 0.4)
        rel = 75 / 100 * 0.3
        soil = 0.7 * 0.2  # loam
        cost = min(0.1, 10000 / 800 * 0.1)
        expected = round(min(1.0, eff + rel + soil + cost), 3)

        result = pond_score(5000, 800, 75, 5, "loam")
        assert result["pondScore"] == expected
