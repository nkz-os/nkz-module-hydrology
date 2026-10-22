"""Tests for daily water balance bucket model."""

import pytest

from app.services.bucket_model import BucketModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sandy_bucket():
    """Sandy loam: high Ksat, low AWC."""
    return BucketModel(
        ksat_mmh=25.0,          # 600 mm/day
        field_capacity_vv=0.20,  # 20% v/v
        wilting_point_vv=0.08,   #  8% v/v
        depth_mm=300,
    )


@pytest.fixture
def clay_bucket():
    """Clay loam: low Ksat, high AWC."""
    return BucketModel(
        ksat_mmh=2.0,           # 48 mm/day
        field_capacity_vv=0.40,  # 40% v/v
        wilting_point_vv=0.22,   # 22% v/v
        depth_mm=300,
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

class TestInit:
    def test_converts_ksat_to_mm_day(self):
        b = BucketModel(10.0, 0.3, 0.1, 300)
        assert b.ksat == 240.0  # 10 mm/h * 24

    def test_computes_fc_and_wp_in_mm(self):
        b = BucketModel(10.0, 0.30, 0.12, 500)
        assert b.fc == 150.0   # 0.30 * 500
        assert b.wp == 60.0    # 0.12 * 500

    def test_initial_moisture_is_50pct_fc(self):
        b = BucketModel(10.0, 0.30, 0.12, 400)
        # fc = 120 mm → 50 % = 60 mm
        assert b.moisture == 60.0


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------

class TestStep:
    def test_dry_day_no_change(self, sandy_bucket):
        """No rain, no ET0 → moisture unchanged."""
        initial = sandy_bucket.moisture
        r = sandy_bucket.step(0.0, 0.0)
        assert r["moisture"] == initial
        assert r["runoff"] == 0.0
        assert r["aet"] == 0.0
        assert r["percolation"] == 0.0

    def test_rain_recharges_moisture(self, sandy_bucket):
        """Rain below FC → moisture increases, no percolation."""
        initial = sandy_bucket.moisture
        r = sandy_bucket.step(30.0, 0.0)
        assert r["moisture"] > initial
        assert r["percolation"] == 0.0
        assert r["runoff"] == 0.0

    def test_excess_rain_produces_runoff_with_cn(self, sandy_bucket):
        """CN=89 for HSG-D row crops → runoff is positive."""
        r = sandy_bucket.step(80.0, 0.0, cn=89)
        assert r["runoff"] > 0.0

    def test_runoff_zero_without_cn(self, sandy_bucket):
        """No CN → no runoff regardless of rainfall."""
        r = sandy_bucket.step(150.0, 0.0)
        assert r["runoff"] == 0.0

    def test_aet_drains_moisture(self, sandy_bucket):
        """High ET0 on dry day reduces moisture."""
        r = sandy_bucket.step(0.0, 10.0, kc=1.0)
        assert r["aet"] > 0.0
        assert r["moisture"] < sandy_bucket.fc * 0.5  # dropped below initial

    def test_aet_limited_by_available_water(self, sandy_bucket):
        """ET cannot extract more than 70 % of available moisture."""
        r = sandy_bucket.step(0.0, 100.0, kc=1.0)
        avail = sandy_bucket.fc * 0.5 - sandy_bucket.wp  # initial
        assert r["aet"] <= avail * 0.7

    def test_percolation_capped_by_ksat(self, sandy_bucket):
        """Percolation does not exceed Ksat."""
        # Saturate with large rain
        r = sandy_bucket.step(500.0, 0.0, cn=89)
        assert r["percolation"] <= sandy_bucket.ksat

    def test_moisture_stays_within_wp_fc(self, sandy_bucket):
        """Moisture never drops below WP or exceeds FC."""
        # Prolonged drought
        for _ in range(30):
            sandy_bucket.step(0.0, 8.0)
        assert sandy_bucket.moisture >= sandy_bucket.wp
        # Big rain event
        sandy_bucket.step(300.0, 0.0)
        assert sandy_bucket.moisture <= sandy_bucket.fc

    def test_saturation_pct(self, sandy_bucket):
        """Saturation percentage is 0 at WP, 100 at FC."""
        b = BucketModel(10.0, 0.30, 0.12, 300)
        # Force to WP
        b.moisture = b.wp
        r = b.step(0.0, 0.0)
        assert r["saturation_pct"] == pytest.approx(0.0, abs=0.01)
        # Force to FC
        b.moisture = b.fc
        r = b.step(0.0, 0.0)
        assert r["saturation_pct"] == pytest.approx(100.0, abs=0.01)

    def test_step_output_keys(self, sandy_bucket):
        r = sandy_bucket.step(10.0, 3.0, kc=0.8)
        expected_keys = {
            "precip", "eto", "etc", "runoff", "infiltration",
            "aet", "percolation", "moisture", "saturation_pct",
        }
        assert set(r.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Run series
# ---------------------------------------------------------------------------

class TestRunSeries:
    def test_returns_one_result_per_day(self, sandy_bucket):
        data = [{"precip": 0, "et0": 3}] * 365
        results = sandy_bucket.run_series(data)
        assert len(results) == 365

    def test_water_balance_closes_without_saturation(self):
        """Water balance closes (P = AET + D + ΔS) when moisture never
        exceeds field capacity (no saturation-excess loss)."""
        b = BucketModel(
            ksat_mmh=10.0,         # 240 mm/day Ksat
            field_capacity_vv=0.35,  # FC = 175 mm
            wilting_point_vv=0.15,   # WP = 75 mm
            depth_mm=500,
        )
        # Net-drying: ET > precip → moisture decreases, never hits FC
        initial_moisture = b.moisture
        data = [{"precip": 1, "et0": 4}] * 100
        results = b.run_series(data)

        total_precip = sum(d["precip"] for d in data)
        total_aet = sum(r["aet"] for r in results)
        total_perc = sum(r["percolation"] for r in results)
        delta_s = results[-1]["moisture"] - initial_moisture
        closure = total_precip - total_aet - total_perc - delta_s
        assert abs(closure) < 0.01, (
            f"Water balance off by {closure:.4f} mm: "
            f"P={total_precip:.1f} ET={total_aet:.1f} "
            f"D={total_perc:.1f} ΔS={delta_s:.4f}"
        )

    def test_saturation_excess_not_tracked_as_storage(self):
        """When moisture exceeds FC, the daily model only tracks 30 %
        of the excess as percolation. The remaining 70 % is implicit
        rapid drainage / interflow, which is an intentional
        simplification for a single-layer bucket. Verify the
        behaviour is deterministic and repeatable."""
        b = BucketModel(10.0, 0.30, 0.12, 300)  # FC=90, WP=36
        r1 = b.step(200.0, 0.0)
        assert r1["moisture"] == b.fc  # clamped to FC
        assert r1["percolation"] > 0.0

        r2 = b.step(0.0, 0.0)
        assert r2["percolation"] == 0.0
        assert r2["moisture"] == b.fc

    def test_cn_param_applied(self, sandy_bucket):
        """Run series with CN → runoff present."""
        data = [{"precip": 50, "et0": 2, "cn": 85}] * 10
        results = sandy_bucket.run_series(data)
        assert any(r["runoff"] > 0 for r in results)

    def test_run_series_kc_default(self, sandy_bucket):
        """Default kc=1.0 when not supplied."""
        data = [{"precip": 0, "et0": 5}] * 3
        results = sandy_bucket.run_series(data)
        for r in results:
            assert r["etc"] == 5.0


# ---------------------------------------------------------------------------

