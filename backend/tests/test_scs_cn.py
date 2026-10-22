"""Tests for SCS Curve Number runoff estimation."""

import pytest

from app.services.scs_cn import HSG_CN_TABLE, cn_for_amc, runoff


# ---------------------------------------------------------------------------
# HSG_CN_TABLE
# ---------------------------------------------------------------------------

class TestHSGCNTable:
    """Verify tabulated CN values against known NEH-4 references."""

    def test_has_expected_keys(self):
        assert ("A", "row_crops") in HSG_CN_TABLE
        assert ("D", "forest") in HSG_CN_TABLE

    def test_row_crops_a_is_67(self):
        assert HSG_CN_TABLE[("A", "row_crops")] == 67

    def test_row_crops_d_is_89(self):
        assert HSG_CN_TABLE[("D", "row_crops")] == 89

    def test_pasture_a_is_49(self):
        assert HSG_CN_TABLE[("A", "pasture")] == 49

    def test_pasture_d_is_84(self):
        assert HSG_CN_TABLE[("D", "pasture")] == 84

    def test_forest_a_is_30(self):
        assert HSG_CN_TABLE[("A", "forest")] == 30

    def test_forest_d_is_77(self):
        assert HSG_CN_TABLE[("D", "forest")] == 77

    def test_hsg_values_ascending(self):
        """CN increases A → D for each land use."""
        for lu in ("row_crops", "pasture", "forest"):
            vals = [HSG_CN_TABLE[(hsg, lu)] for hsg in ("A", "B", "C", "D")]
            assert vals == sorted(vals), f"{lu}: CN not monotonic"


# ---------------------------------------------------------------------------
# cn_for_amc
# ---------------------------------------------------------------------------

class TestCNForAMC:
    def test_amc_ii_returns_same(self):
        assert cn_for_amc(78, "II") == 78.0

    def test_amc_i_lower_than_cn2(self):
        cn1 = cn_for_amc(78, "I")
        assert cn1 < 78

    def test_amc_iii_higher_than_cn2(self):
        cn3 = cn_for_amc(78, "III")
        assert cn3 > 78

    def test_known_amc_i_value(self):
        """CN(I) = CN(II) / (2.281 - 0.01281 * CN(II)).

        For CN(II)=78: CN(I)=78/(2.281-0.01281*78)
        """
        expected = 78 / (2.281 - 0.01281 * 78)
        assert cn_for_amc(78, "I") == pytest.approx(expected, abs=1e-9)

    def test_known_amc_iii_value(self):
        """CN(III) = CN(II) / (0.427 + 0.00573 * CN(II))."""
        expected = 78 / (0.427 + 0.00573 * 78)
        assert cn_for_amc(78, "III") == pytest.approx(expected, abs=1e-9)

    def test_low_cn_amc_i_not_negative(self):
        assert cn_for_amc(30, "I") > 0

    def test_high_cn_amc_iii_less_than_100(self):
        assert cn_for_amc(95, "III") < 100


# ---------------------------------------------------------------------------
# runoff
# ---------------------------------------------------------------------------

class TestRunoff:
    def test_zero_runoff_when_precip_below_Ia(self):
        """S=25400/CN-254, Ia=0.2S. P <= Ia → no runoff."""
        # CN=70 → S≈108.9, Ia≈21.8 → precip=10 < Ia
        q, qp = runoff(10.0, 70)
        assert q == 0.0
        assert qp == 0.0

    def test_positive_runoff_for_large_storm(self):
        q, qp = runoff(100.0, 78)
        assert q > 0
        assert qp > 0

    def test_cn_100_high_runoff(self):
        """CN=100 → S=0, Ia=0 → all rain becomes runoff."""
        q, qp = runoff(50.0, 100)
        assert q == pytest.approx(50.0, abs=0.01)

    def test_peak_flow_positive_with_runoff(self):
        q, qp = runoff(80.0, 85)
        assert qp > 0
        # Default area_ha=100 → 1 km²; default tc_h=0.5
        # qp = 0.208 * Q * 1.0 / 0.5 = 0.208 * Q * 2
        assert qp == pytest.approx(0.208 * q * 2, abs=1e-9)

    def test_monotonic_with_cn(self):
        """Higher CN → higher runoff for same rainfall."""
        q_low = runoff(80, 60)[0]
        q_high = runoff(80, 85)[0]
        assert q_high > q_low

    def test_monotonic_with_precip(self):
        """More rain → more runoff for same CN."""
        q_small = runoff(30, 78)[0]
        q_large = runoff(80, 78)[0]
        assert q_large >= q_small

    def test_returns_tuple_of_floats(self):
        result = runoff(100.0, 78)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)


# ---------------------------------------------------------------------------
# runoff with area_ha / tc_h (parametrized peak flow)
# ---------------------------------------------------------------------------

class TestRunoffWithArea:
    def test_double_area_doubles_peak_flow(self):
        """Peak flow scales linearly with area for same Q and Tc."""
        q1, qp1 = runoff(50.0, 78, area_ha=50.0, tc_h=1.0)
        q2, qp2 = runoff(50.0, 78, area_ha=100.0, tc_h=1.0)
        assert q1 == q2  # runoff depth unchanged
        assert qp2 == pytest.approx(qp1 * 2.0, rel=0.01)

    def test_half_tc_doubles_peak_flow(self):
        """Peak flow inversely proportional to Tc."""
        _, qp1 = runoff(50.0, 78, area_ha=100.0, tc_h=2.0)
        _, qp2 = runoff(50.0, 78, area_ha=100.0, tc_h=1.0)
        assert qp2 == pytest.approx(qp1 * 2.0, rel=0.01)

    def test_hectares_are_converted_to_km2(self):
        """SCS formula expects km², not ha. 100 ha = 1 km².
        Peak flow for 100 ha must equal peak flow for 1 km²."""
        _, qp_ha = runoff(50.0, 78, area_ha=100.0, tc_h=1.0)
        # Q ≈ 11.86mm for CN=78 P=50; A=1km² Tc=1h → qp = 0.208*11.86*1/1 ≈ 2.47
        assert qp_ha == pytest.approx(2.47, rel=0.05)

    def test_peak_flow_is_reasonable_for_small_parcel(self):
        """A 5-ha parcel with 50mm rain and CN 78 → peak flow ~0.25 m³/s.
        With the old bug (no ha→km² conversion) this would be ~25 m³/s,
        which is absurd for 5 ha."""
        _, qp = runoff(50.0, 78, area_ha=5.0, tc_h=0.5)
        # Q ≈ 11.86mm, A=0.05km², Tc=0.5h → qp = 0.208*11.86*0.05/0.5 ≈ 0.247
        assert qp == pytest.approx(0.247, rel=0.05)
        assert qp < 2.0  # sanity: not absurdly high
