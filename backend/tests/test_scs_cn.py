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
        # qp = 0.208 * Q * 100 / 0.5
        assert qp == pytest.approx(0.208 * q * 200, abs=1e-9)

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
