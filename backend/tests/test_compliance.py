"""Tests for regulatory compliance — permit thresholds, breach risk, exposure."""

import pytest

from app.services.compliance import (
    PERMIT_THRESHOLDS_M3,
    requires_water_permit,
    breach_risk_class,
    downstream_exposure,
)


# ---------------------------------------------------------------------------
# requires_water_permit
# ---------------------------------------------------------------------------

class TestRequiresWaterPermit:
    """Verify permit threshold logic across basins."""

    def test_volume_below_threshold_returns_false(self):
        """6000 m³ in CH_Ebro (threshold 7000) → no permit needed."""
        assert requires_water_permit(6000, "CH_Ebro") is False

    def test_volume_above_threshold_returns_true(self):
        """6000 m³ in CH_Segura (threshold 3000) → permit needed."""
        assert requires_water_permit(6000, "CH_Segura") is True

    def test_volume_at_threshold_returns_false(self):
        """Exactly at threshold → no permit (strict >)."""
        assert requires_water_permit(7000, "CH_Ebro") is False

    def test_volume_at_threshold_plus_one_returns_true(self):
        assert requires_water_permit(7001, "CH_Ebro") is True

    def test_unknown_basin_falls_back_to_default(self):
        """Unrecognised basin → default threshold 5000."""
        assert requires_water_permit(4000, "CH_Unknown") is False
        assert requires_water_permit(6000, "CH_Unknown") is True

    def test_default_basin_matches_default_threshold(self):
        assert requires_water_permit(5000, "default") is False
        assert requires_water_permit(5001, "default") is True

    def test_zero_volume_never_requires_permit(self):
        assert requires_water_permit(0, "CH_Segura") is False

    def test_all_basins_have_thresholds_in_dict(self):
        """Every recognised basin has an entry in the threshold dict."""
        known = [
            "CH_Ebro", "CH_Duero", "CH_Tajo", "CH_Guadiana",
            "CH_Guadalquivir", "CH_Segura", "CH_Jucar",
            "CH_Ebro_Cataluna", "CH_Minho_Sil", "CH_Cantabrico",
        ]
        for b in known:
            assert b in PERMIT_THRESHOLDS_M3
            assert isinstance(PERMIT_THRESHOLDS_M3[b], int)
            assert PERMIT_THRESHOLDS_M3[b] > 0


# ---------------------------------------------------------------------------
# breach_risk_class
# ---------------------------------------------------------------------------

class TestBreachRiskClass:
    """Verify risk classification scoring."""

    def test_low_risk_all_low_inputs(self):
        """Small volume, gentle slope, no exposure → low."""
        assert breach_risk_class(1000, 2, False) == "low"

    def test_low_risk_single_volume_increment(self):
        """Volume > 5000 alone → score 1 → low (needs ≥ 2 for medium)."""
        assert breach_risk_class(6000, 2, False) == "low"

    def test_low_risk_single_slope_increment(self):
        """Slope > 5 % alone → score 1 → low (needs ≥ 2 for medium)."""
        assert breach_risk_class(1000, 8, False) == "low"

    def test_high_risk_volume_and_slope(self):
        """> 5000 + > 5 % → score 2 → medium (need 3 for high)."""
        # 5000+ = +1, slope > 5 = +1, total = 2 → medium
        assert breach_risk_class(6000, 8, False) == "medium"

    def test_high_risk_with_downstream_exposure(self):
        """> 5000 + exposure → score 3 → high."""
        assert breach_risk_class(6000, 2, True) == "high"

    def test_high_risk_large_volume_and_exposure(self):
        """> 20000 + exposure → score 4 → high."""
        assert breach_risk_class(25000, 2, True) == "high"

    def test_high_risk_volume_only_two_big_triggers(self):
        """> 5000 (=1) + > 20000 (=+1) → score 2 → medium."""
        assert breach_risk_class(25000, 2, False) == "medium"

    def test_high_risk_all_triggers(self):
        """> 5000 + > 20000 + slope > 5 + exposure → score 5 → high."""
        assert breach_risk_class(25000, 8, True) == "high"

    def test_volume_exactly_5000_is_not_an_increment(self):
        """Exactly 5000 → no score from volume (not > 5000)."""
        assert breach_risk_class(5000, 2, False) == "low"

    def test_slope_exactly_5_is_not_an_increment(self):
        """Exactly 5 % → no score from slope (not > 5)."""
        assert breach_risk_class(1000, 5, False) == "low"

    def test_exposure_adds_two_points(self):
        """Downstream exposure alone → score 2 → medium."""
        assert breach_risk_class(1000, 2, True) == "medium"


# ---------------------------------------------------------------------------
# downstream_exposure
# ---------------------------------------------------------------------------

class TestDownstreamExposure:
    """Verify exposure detection for infrastructure."""

    def test_no_features_no_exposure(self):
        result = downstream_exposure((0, 0), [], [], [])
        assert result["has_exposure"] is False
        assert result["affected_buildings"] == 0
        assert result["affected_roads"] == 0
        assert result["affected_streams"] == 0

    def test_buildings_trigger_exposure(self):
        result = downstream_exposure((0, 0), [{"id": 1}, {"id": 2}], [], [])
        assert result["has_exposure"] is True
        assert result["affected_buildings"] == 2

    def test_roads_trigger_exposure(self):
        result = downstream_exposure((0, 0), [], [{"id": 1}], [])
        assert result["has_exposure"] is True
        assert result["affected_roads"] == 1

    def test_streams_do_not_trigger_exposure(self):
        """Streams alone do not set has_exposure (only buildings/roads)."""
        result = downstream_exposure((0, 0), [], [], [{"id": 1}])
        assert result["has_exposure"] is False
        assert result["affected_streams"] == 1

    def test_all_features_counted(self):
        result = downstream_exposure(
            (0, 0),
            [{"id": 1}],
            [{"id": 2}, {"id": 3}],
            [{"id": 4}],
        )
        assert result["has_exposure"] is True
        assert result["affected_buildings"] == 1
        assert result["affected_roads"] == 2
        assert result["affected_streams"] == 1

    def test_pond_location_passed_but_not_used(self):
        """Current simplified impl accepts location but doesn't use it."""
        result = downstream_exposure((42.0, -3.5), [], [], [])
        assert result["has_exposure"] is False

    def test_returns_expected_keys(self):
        result = downstream_exposure((0, 0), [], [], [])
        assert set(result.keys()) == {
            "has_exposure", "affected_buildings", "affected_roads",
            "affected_streams",
        }
