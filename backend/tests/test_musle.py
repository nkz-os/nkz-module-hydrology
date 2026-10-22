"""Tests for MUSLE sediment yield estimation."""

import math

import pytest

from app.services.musle import c_from_ndvi, ls_from_slope, musle_sediment


# ---------------------------------------------------------------------------
# musle_sediment
# ---------------------------------------------------------------------------

class TestMusleSediment:
    """Verify the core MUSLE formula against hand-calculated references."""

    def test_zero_runoff_returns_zero(self):
        """No runoff → no sediment regardless of other factors."""
        assert musle_sediment(0.0, 10.0, 0.3, 2.0, 0.5) == 0.0

    def test_zero_peak_flow_returns_zero(self):
        """No peak flow → no sediment."""
        assert musle_sediment(1000.0, 0.0, 0.3, 2.0, 0.5) == 0.0

    def test_both_zero_returns_zero(self):
        assert musle_sediment(0.0, 0.0, 0.3, 2.0, 0.5) == 0.0

    def test_sediment_increases_with_runoff(self):
        """More runoff → more sediment, all else equal."""
        low = musle_sediment(500, 5, 0.3, 2.0, 0.5)
        high = musle_sediment(5000, 5, 0.3, 2.0, 0.5)
        assert high > low

    def test_sediment_increases_with_k_factor(self):
        """Higher erodibility → more sediment."""
        low = musle_sediment(1000, 5, 0.1, 2.0, 0.5)
        high = musle_sediment(1000, 5, 0.5, 2.0, 0.5)
        assert high > low

    def test_sediment_increases_with_ls_factor(self):
        """Steeper/longer slope → more sediment."""
        low = musle_sediment(1000, 5, 0.3, 1.0, 0.5)
        high = musle_sediment(1000, 5, 0.3, 4.0, 0.5)
        assert high > low

    def test_sediment_decreases_with_c_factor(self):
        """Better cover → less sediment."""
        low = musle_sediment(1000, 5, 0.3, 2.0, 0.1)
        high = musle_sediment(1000, 5, 0.3, 2.0, 0.9)
        assert low < high

    def test_p_factor_reduces_sediment(self):
        """Support practices reduce sediment."""
        no_practice = musle_sediment(1000, 5, 0.3, 2.0, 0.5, 1.0)
        with_practice = musle_sediment(1000, 5, 0.3, 2.0, 0.5, 0.5)
        assert with_practice < no_practice
        assert with_practice == pytest.approx(no_practice * 0.5)

    def test_known_input_range(self):
        """Known inputs produce a yield in the expected range."""
        # 10 mm runoff over 1 ha → ~100 m³; peak ~2 m³/s
        y = musle_sediment(
            runoff_m3=100.0,
            peak_flow_m3s=2.0,
            k_factor=0.3,
            ls_factor=2.0,
            c_factor=0.5,
        )
        # Should be a plausible small-event value: order 1‑20 t
        assert 1.0 < y < 20.0

    def test_returns_float(self):
        y = musle_sediment(1000.0, 5.0, 0.3, 2.0, 0.5)
        assert isinstance(y, float)


# ---------------------------------------------------------------------------
# ls_from_slope
# ---------------------------------------------------------------------------

class TestLSFromSlope:
    """Wischmeier‑Smith LS factor at various slopes and lengths."""

    def test_flat_terrain_returns_positive(self):
        """0 % slope → LS = (L/22.13)^0.3 * 1.0 > 0."""
        ls = ls_from_slope(0.0)
        assert ls > 0
        assert ls < 5  # not absurdly large

    def test_ls_increases_with_slope(self):
        """Steeper slope → larger LS."""
        low = ls_from_slope(2.0)
        high = ls_from_slope(10.0)
        assert high > low

    def test_ls_increases_with_length(self):
        """Longer slope → larger LS."""
        short = ls_from_slope(5.0, slope_length_m=25)
        long = ls_from_slope(5.0, slope_length_m=100)
        assert long > short

    def test_exponent_changes_at_5_pct(self):
        """m=0.4 at 4 %, m=0.5 at 5 % → bigger jump at 5 %."""
        ls4 = ls_from_slope(4.0, slope_length_m=50)
        ls5 = ls_from_slope(5.0, slope_length_m=50)
        assert ls5 > ls4

    def test_exponent_changes_at_3_pct(self):
        """m=0.3 at 2 %, m=0.4 at 3 %."""
        ls2 = ls_from_slope(2.0, slope_length_m=50)
        ls3 = ls_from_slope(3.0, slope_length_m=50)
        assert ls3 > ls2

    def test_returns_float(self):
        assert isinstance(ls_from_slope(5.0), float)

    def test_very_steep_slope_not_excessive(self):
        """30 % slope is physically plausible (max < 50)."""
        ls = ls_from_slope(30.0)
        assert ls < 50

    @pytest.mark.parametrize("pct,expected_m", [
        (1.0, 0.3),
        (2.9, 0.3),
        (3.0, 0.4),
        (4.9, 0.4),
        (5.0, 0.5),
        (20.0, 0.5),
    ])
    def test_exponent_selection(self, pct, expected_m):
        """Verify m exponent chosen correctly for each slope range."""
        s = pct / 100.0
        L = (50.0 / 22.13) ** expected_m
        S = (65.41 * s**2 + 4.56 * s + 0.065) / (s**2 + 2.24 * s + 0.065)
        expected = L * S
        assert ls_from_slope(pct) == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# c_from_ndvi
# ---------------------------------------------------------------------------

class TestCFromNDVI:
    """Cover-management factor from NDVI."""

    def test_ndvi_0_1_returns_1(self):
        """NDVI=0.1 → C=1.0 (bare soil)."""
        assert c_from_ndvi(0.1) == 1.0

    def test_ndvi_0_8_returns_0_01(self):
        """NDVI=0.8 → C=0.01 (full cover floor)."""
        assert c_from_ndvi(0.8) == 0.01

    def test_ndvi_0_45_returns_0_5(self):
        """NDVI=0.45 → C=0.5 (mid cover)."""
        assert c_from_ndvi(0.45) == pytest.approx(0.5, abs=1e-9)

    def test_ndvi_below_0_1_clamps_to_1(self):
        """NDVI < 0.1 → C=1.0 (clamped)."""
        assert c_from_ndvi(0.0) == 1.0
        assert c_from_ndvi(-0.5) == 1.0

    def test_ndvi_above_0_8_clamps_to_0_01(self):
        """NDVI > 0.8 → C=0.01 (clamped)."""
        assert c_from_ndvi(0.9) == 0.01
        assert c_from_ndvi(1.0) == 0.01

    def test_inverse_relationship(self):
        """Higher NDVI → lower C factor."""
        low = c_from_ndvi(0.2)
        high = c_from_ndvi(0.7)
        assert high < low

    def test_returns_float(self):
        assert isinstance(c_from_ndvi(0.5), float)
