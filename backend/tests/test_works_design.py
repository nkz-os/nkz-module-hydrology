"""Tests for works design helpers (swales, check dams, sediment)."""

import pytest

from app.services.works_design import (
    check_dam_sediment_retention,
    check_dam_spacing,
    swale_capacity,
)


# ---------------------------------------------------------------------------
# swale_capacity
# ---------------------------------------------------------------------------

class TestSwaleCapacity:
    """Infiltration capacity of a swale during a design storm."""

    def test_capacity_scales_with_ksat(self):
        """Higher Ksat → higher infiltration rate and volume."""
        low = swale_capacity(ksat_mmh=5, wetted_perimeter_m=3, length_m=100)
        high = swale_capacity(ksat_mmh=20, wetted_perimeter_m=3, length_m=100)
        assert high["infilt_rate_m3h"] > low["infilt_rate_m3h"]
        assert high["volume_m3"] > low["volume_m3"]
        # 4× Ksat → 4× rate/volume
        assert high["infilt_rate_m3h"] == pytest.approx(
            low["infilt_rate_m3h"] * 4
        )

    def test_capacity_scales_with_wetted_perimeter(self):
        """Wider perimeter → more infiltration."""
        narrow = swale_capacity(10, 2, 100)
        wide = swale_capacity(10, 6, 100)
        assert wide["volume_m3"] > narrow["volume_m3"]
        assert wide["infilt_rate_m3h"] == pytest.approx(
            narrow["infilt_rate_m3h"] * 3
        )

    def test_capacity_scales_with_length(self):
        """Longer swale → more infiltration."""
        short = swale_capacity(10, 3, 50)
        long = swale_capacity(10, 3, 200)
        assert long["volume_m3"] > short["volume_m3"]
        assert long["infilt_rate_m3h"] == pytest.approx(
            short["infilt_rate_m3h"] * 4
        )

    def test_default_fill_time_is_24h(self):
        """Default 24 h fill time used when not specified."""
        result = swale_capacity(10, 3, 100)
        # rate = 10 * 3 * 100 / 1000 = 3 m³/h
        assert result["infilt_rate_m3h"] == pytest.approx(3.0)
        assert result["volume_m3"] == pytest.approx(3.0 * 24)

    def test_custom_fill_time_applied(self):
        """Custom fill time overrides default."""
        result = swale_capacity(10, 3, 100, fill_time_h=12)
        assert result["volume_m3"] == pytest.approx(36.0)

    def test_zero_ksat_yields_zero(self):
        """No infiltration → zero volume."""
        result = swale_capacity(0, 3, 100)
        assert result["volume_m3"] == 0.0
        assert result["infilt_rate_m3h"] == 0.0

    def test_known_value(self):
        """Ksat=15, perimeter=4, length=80, 24h → rate=4.8 m³/h,
        volume=115.2 m³."""
        result = swale_capacity(15, 4, 80)
        assert result["infilt_rate_m3h"] == pytest.approx(4.8)
        assert result["volume_m3"] == pytest.approx(115.2)

    def test_returns_expected_keys(self):
        result = swale_capacity(10, 3, 100)
        assert set(result.keys()) == {"volume_m3", "infilt_rate_m3h"}


# ---------------------------------------------------------------------------
# check_dam_spacing
# ---------------------------------------------------------------------------

class TestCheckDamSpacing:
    """Crest‑to‑toe spacing rule."""

    def test_spacing_for_typical_slope(self):
        """5 % slope, 1 m dam → 20 m spacing."""
        assert check_dam_spacing(0.05, 1.0) == pytest.approx(20.0)

    def test_higher_dam_more_spacing(self):
        """Taller dam → wider spacing."""
        short = check_dam_spacing(0.05, 0.5)
        tall = check_dam_spacing(0.05, 2.0)
        assert tall > short

    def test_steeper_slope_less_spacing(self):
        """Steeper slope → narrower spacing."""
        gentle = check_dam_spacing(0.02, 1.0)
        steep = check_dam_spacing(0.10, 1.0)
        assert steep < gentle

    def test_zero_slope_returns_zero(self):
        assert check_dam_spacing(0.0, 1.0) == 0.0

    def test_negative_slope_returns_zero(self):
        assert check_dam_spacing(-0.05, 1.0) == 0.0

    def test_inverse_relationship(self):
        """spacing = height / slope → slope halved → spacing doubled."""
        original = check_dam_spacing(0.04, 1.0)
        half_slope = check_dam_spacing(0.02, 1.0)
        assert half_slope == pytest.approx(original * 2)

    def test_returns_float(self):
        assert isinstance(check_dam_spacing(0.05, 1.0), float)


# ---------------------------------------------------------------------------
# check_dam_sediment_retention
# ---------------------------------------------------------------------------

class TestCheckDamSedimentRetention:
    """Sediment mass behind a check dam."""

    def test_retention_increases_with_height(self):
        """Taller dam → more sediment (quadratic in height)."""
        low = check_dam_sediment_retention(0.5, 10)
        high = check_dam_sediment_retention(1.0, 10)
        # height² → 2× height → 4× volume
        assert high == pytest.approx(low * 4)

    def test_retention_increases_with_width(self):
        """Wider dam → more sediment (linear)."""
        narrow = check_dam_sediment_retention(1.0, 5)
        wide = check_dam_sediment_retention(1.0, 20)
        assert wide == pytest.approx(narrow * 4)

    def test_default_bulk_density_1_3(self):
        """Default bulk density 1.3 t/m³."""
        result = check_dam_sediment_retention(1.0, 10)
        # volume = 1² × 10 / 2 = 5 m³; mass = 5 × 1.3 = 6.5 t
        assert result == pytest.approx(6.5)

    def test_custom_bulk_density(self):
        result = check_dam_sediment_retention(1.0, 10, bulk_density_tm3=1.5)
        assert result == pytest.approx(7.5)

    def test_known_value(self):
        """height=0.8, width=12, bulk=1.3 → vol=3.84 m³, mass≈4.992."""
        result = check_dam_sediment_retention(0.8, 12)
        assert result == pytest.approx(4.992)

    def test_zero_height_returns_zero(self):
        assert check_dam_sediment_retention(0, 10) == 0.0

    def test_zero_width_returns_zero(self):
        assert check_dam_sediment_retention(1.0, 0) == 0.0

    def test_returns_float(self):
        assert isinstance(check_dam_sediment_retention(1.0, 10), float)
