"""Tests for rule-based hydrologic alert system."""

import pytest

from app.services.alerts import (
    AlertMechanism,
    AlertSeverity,
    evaluate_alerts,
)


# ---------------------------------------------------------------------------
# No alerts under normal conditions
# ---------------------------------------------------------------------------

class TestNoAlerts:
    """Verify that normal conditions produce no alerts."""

    @staticmethod
    def normal_state(**overrides) -> dict:
        state = {"saturation_pct": 40, "precip": 0, "et0": 3, "moisture": 60}
        state.update(overrides)
        return state

    def test_dry_soil_no_rain(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=0, ndvi=0.7, slope_pct=2
        )
        assert alerts == []

    def test_vegetated_soil_moderate_rain(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 50}, forecast_precip=15, ndvi=0.6, slope_pct=5
        )
        assert alerts == []

    def test_high_ndvi_intense_rain_no_alert(self):
        """Hortonian only triggers with low NDVI."""
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=50, ndvi=0.6, slope_pct=3
        )
        assert alerts == []


# ---------------------------------------------------------------------------
# Saturation excess
# ---------------------------------------------------------------------------

class TestSaturationExcess:
    """Dunne-type runoff alerts."""

    def test_critical_when_saturated_and_rain(self):
        """sat > 80 % + precip > 10 mm → CRITICAL."""
        alerts = evaluate_alerts(
            {"saturation_pct": 85}, forecast_precip=15, ndvi=0.5, slope_pct=2
        )
        critical = [a for a in alerts if a["severity"] == AlertSeverity.CRITICAL]
        assert len(critical) == 1
        assert critical[0]["mechanism"] == AlertMechanism.SATURATION_EXCESS

    def test_critical_edge_lower_bound(self):
        """sat=80.1, precip=10.1 → just barely critical."""
        alerts = evaluate_alerts(
            {"saturation_pct": 80.1}, forecast_precip=10.1, ndvi=0.5, slope_pct=2
        )
        assert any(
            a["severity"] == AlertSeverity.CRITICAL for a in alerts
        )

    def test_warning_when_near_saturated_and_rain(self):
        """sat > 60 % + precip > 20 mm → WARNING."""
        alerts = evaluate_alerts(
            {"saturation_pct": 65}, forecast_precip=25, ndvi=0.5, slope_pct=2
        )
        warnings = [a for a in alerts if a["severity"] == AlertSeverity.WARNING]
        assert any(a["mechanism"] == AlertMechanism.SATURATION_EXCESS for a in warnings)

    def test_warning_edge_lower_bound(self):
        """sat=60.1, precip=20.1 → just barely warning."""
        alerts = evaluate_alerts(
            {"saturation_pct": 60.1}, forecast_precip=20.1, ndvi=0.5, slope_pct=2
        )
        assert any(
            a["severity"] == AlertSeverity.WARNING
            and a["mechanism"] == AlertMechanism.SATURATION_EXCESS
            for a in alerts
        )

    def test_critical_takes_priority_over_warning(self):
        """Sat > 80 + precip > 10 → only CRITICAL, not also WARNING."""
        alerts = evaluate_alerts(
            {"saturation_pct": 90}, forecast_precip=30, ndvi=0.5, slope_pct=2
        )
        sat_alerts = [
            a for a in alerts
            if a["mechanism"] == AlertMechanism.SATURATION_EXCESS
        ]
        assert len(sat_alerts) == 1
        assert sat_alerts[0]["severity"] == AlertSeverity.CRITICAL

    def test_no_alert_when_sat_below_60(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 55}, forecast_precip=50, ndvi=0.5, slope_pct=2
        )
        sat_alerts = [
            a for a in alerts
            if a["mechanism"] == AlertMechanism.SATURATION_EXCESS
        ]
        assert len(sat_alerts) == 0

    def test_no_alert_when_saturated_but_no_rain(self):
        """precip <= 10 with sat > 80 → no critical."""
        alerts = evaluate_alerts(
            {"saturation_pct": 85}, forecast_precip=5, ndvi=0.5, slope_pct=2
        )
        assert len(alerts) == 0

    def test_no_warning_when_precip_below_threshold(self):
        """precip <= 20 with sat > 60 → no warning."""
        alerts = evaluate_alerts(
            {"saturation_pct": 70}, forecast_precip=15, ndvi=0.5, slope_pct=2
        )
        sat_warnings = [
            a for a in alerts
            if a["mechanism"] == AlertMechanism.SATURATION_EXCESS
        ]
        assert len(sat_warnings) == 0


# ---------------------------------------------------------------------------
# Infiltration excess
# ---------------------------------------------------------------------------

class TestInfiltrationExcess:
    """Hortonian-type runoff alerts."""

    def test_warning_on_bare_soil_and_intense_rain(self):
        """ndvi < 0.3 + precip > 25 → WARNING."""
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=30, ndvi=0.2, slope_pct=5
        )
        hortonian = [a for a in alerts if a["severity"] == AlertSeverity.WARNING]
        assert any(
            a["mechanism"] == AlertMechanism.INFILTRATION_EXCESS
            for a in hortonian
        )

    def test_warning_edge_lower_bound(self):
        """ndvi=0.29, precip=25.1 → barely warning."""
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=25.1, ndvi=0.29, slope_pct=5
        )
        assert any(
            a["mechanism"] == AlertMechanism.INFILTRATION_EXCESS
            for a in alerts
        )

    def test_no_alert_when_ndvi_above_0_3(self):
        """ndvi >= 0.3 → no infiltration excess alert."""
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=50, ndvi=0.35, slope_pct=5
        )
        hortonian = [
            a for a in alerts
            if a["mechanism"] == AlertMechanism.INFILTRATION_EXCESS
        ]
        assert len(hortonian) == 0

    def test_no_alert_when_precip_below_25(self):
        """precip <= 25 → no infiltration excess alert."""
        alerts = evaluate_alerts(
            {"saturation_pct": 30}, forecast_precip=20, ndvi=0.1, slope_pct=5
        )
        hortonian = [
            a for a in alerts
            if a["mechanism"] == AlertMechanism.INFILTRATION_EXCESS
        ]
        assert len(hortonian) == 0


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------

class TestCombinedAlerts:
    """Scenarios where both mechanisms could trigger."""

    def test_both_mechanisms_can_coexist(self):
        """Saturated + bare soil + heavy rain → both alerts."""
        alerts = evaluate_alerts(
            {"saturation_pct": 85}, forecast_precip=50, ndvi=0.2, slope_pct=5
        )
        mechanisms = {a["mechanism"] for a in alerts}
        assert AlertMechanism.SATURATION_EXCESS in mechanisms
        assert AlertMechanism.INFILTRATION_EXCESS in mechanisms
        assert len(alerts) == 2

    def test_saturation_critical_and_hortonian_warning(self):
        """Highest severity for each mechanism."""
        alerts = evaluate_alerts(
            {"saturation_pct": 90}, forecast_precip=50, ndvi=0.2, slope_pct=5
        )
        sat = [a for a in alerts if a["mechanism"] == AlertMechanism.SATURATION_EXCESS]
        hor = [a for a in alerts if a["mechanism"] == AlertMechanism.INFILTRATION_EXCESS]
        assert sat[0]["severity"] == AlertSeverity.CRITICAL
        assert hor[0]["severity"] == AlertSeverity.WARNING


# ---------------------------------------------------------------------------
# Alert dict structure
# ---------------------------------------------------------------------------

class TestAlertStructure:
    """Every returned alert must have the standard keys."""

    def test_alert_has_required_keys(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 85}, forecast_precip=15, ndvi=0.2, slope_pct=5
        )
        for alert in alerts:
            assert "severity" in alert
            assert "mechanism" in alert
            assert "description" in alert

    def test_severity_is_valid_enum(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 90}, forecast_precip=30, ndvi=0.1, slope_pct=5
        )
        for alert in alerts:
            assert alert["severity"] in (AlertSeverity.INFO, AlertSeverity.WARNING, AlertSeverity.CRITICAL)

    def test_mechanism_is_valid_enum(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 90}, forecast_precip=30, ndvi=0.1, slope_pct=5
        )
        for alert in alerts:
            assert alert["mechanism"] in (AlertMechanism.SATURATION_EXCESS, AlertMechanism.INFILTRATION_EXCESS)

    def test_description_is_string(self):
        alerts = evaluate_alerts(
            {"saturation_pct": 85}, forecast_precip=15, ndvi=0.5, slope_pct=2
        )
        for alert in alerts:
            assert isinstance(alert["description"], str)
            assert len(alert["description"]) > 0
