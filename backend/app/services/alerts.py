"""
Rule-based hydrologic alert system for NKZ Water Studio.

Combines bucket-model state (soil saturation), weather forecast
(precipitation), and NDVI-derived cover to detect and classify
runoff-generating mechanisms:

* **Saturation excess (Dunne)** — soil is near or at field capacity
  and additional rainfall cannot infiltrate.
* **Infiltration excess (Hortonian)** — rainfall intensity exceeds
  infiltration capacity, typically on bare or sparsely vegetated soil.
"""

from __future__ import annotations

from enum import Enum


class AlertSeverity(str, Enum):
    """Alert urgency level."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertMechanism(str, Enum):
    """Hydrologic mechanism driving the alert."""

    SATURATION_EXCESS = "saturationExcess"
    INFILTRATION_EXCESS = "infiltrationExcess"


def evaluate_alerts(
    bucket_state: dict,
    forecast_precip: float,
    ndvi: float,
    slope_pct: float,
) -> list[dict]:
    """Evaluate hydrologic alerts based on current parcel state.

    Parameters
    ----------
    bucket_state : dict
        Bucket-model state dictionary.  Must contain at least a
        ``"saturation_pct"`` key (0‑100).
    forecast_precip : float
        Forecast precipitation depth (mm).
    ndvi : float
        Current NDVI value.
    slope_pct : float
        Slope steepness (percent).

    Returns
    -------
    list[dict]
        List of alert dictionaries, each with keys:

        * ``severity`` (AlertSeverity)
        * ``mechanism`` (AlertMechanism)
        * ``description`` (str)
    """
    alerts: list[dict] = []
    sat = bucket_state.get("saturation_pct", 0.0)

    # --- Saturation excess (Dunne) ----------------------------------------
    if sat > 80 and forecast_precip > 10:
        alerts.append({
            "severity": AlertSeverity.CRITICAL,
            "mechanism": AlertMechanism.SATURATION_EXCESS,
            "description": (
                f"Soil saturated ({sat:.0f}%) + {forecast_precip}mm "
                f"forecast — imminent saturation-excess runoff"
            ),
        })
    elif sat > 60 and forecast_precip > 20:
        alerts.append({
            "severity": AlertSeverity.WARNING,
            "mechanism": AlertMechanism.SATURATION_EXCESS,
            "description": (
                f"Soil near saturation ({sat:.0f}%) — "
                f"watch for runoff if rain intensifies"
            ),
        })

    # --- Infiltration excess (Hortonian) -----------------------------------
    if ndvi < 0.3 and forecast_precip > 25:
        alerts.append({
            "severity": AlertSeverity.WARNING,
            "mechanism": AlertMechanism.INFILTRATION_EXCESS,
            "description": (
                f"Bare soil (NDVI={ndvi:.2f}) + {forecast_precip}mm "
                f"forecast — risk of infiltration-excess runoff"
            ),
        })

    return alerts
