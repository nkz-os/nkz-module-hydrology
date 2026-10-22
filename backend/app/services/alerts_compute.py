"""On-demand hydrologic alert evaluation (Phase 2A — reactive).

Reads the latest hydrology AgriParcelRecord (soil saturation, observed precip,
slope) and evaluates saturation-excess (Dunne) / infiltration-excess (Hortonian)
runoff risk via ``alerts.evaluate_alerts``. Always current — no webhook, no
stale state, no unauthenticated state mutation.

ASSUMPTIONS (2B refines these):
- ``ndvi`` is not persisted on the record → defaults to 0.5 (moderate cover)
  until EOProduct NDVI is wired in (otherwise bare-soil pixels would always
  trigger Hortonian alerts on the default).
- ``precip`` is the pipeline's OBSERVED value, used as the forecast proxy
  (reactive, not predictive). Predictive alerts need the weather-map forecast
  endpoint (verified available — Phase 2B).
"""
from __future__ import annotations

from nkz_platform_sdk import SyncOrionClient

from app.services.alerts import evaluate_alerts
from app.services.hydro_record import latest_hydro_record, num_attr

_DEFAULT_NDVI = 0.5


def compute_alerts(tenant_id: str, parcel_id: str) -> dict:
    """Evaluate active hydrologic alerts for a parcel from its latest record."""
    orion = SyncOrionClient(tenant_id)
    record = latest_hydro_record(orion, parcel_id)
    if not record:
        return {"status": "no_data"}

    sat = num_attr(record.get("nkz:soilSaturationPct")) or 0.0
    precip = num_attr(record.get("nkz:precipitationMm")) or 0.0
    slope = num_attr(record.get("nkz:slopeMean")) or 0.0
    ndvi = num_attr(record.get("nkz:ndvi")) or _DEFAULT_NDVI

    alerts = evaluate_alerts(
        bucket_state={"saturation_pct": sat},
        forecast_precip=precip,
        ndvi=ndvi,
        slope_pct=slope,
    )

    return {
        "status": "ok",
        "alerts": alerts,
        "inputs": {
            "soilSaturationPct": round(sat, 1),
            "precipitationMm": round(precip, 1),
            "slopeMean": round(slope, 1),
            "ndvi": round(ndvi, 2),
        },
    }
