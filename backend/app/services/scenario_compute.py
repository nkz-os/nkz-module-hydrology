"""On-demand baseline-vs-intervention scenario comparison.

Computed live from the latest hydrology AgriParcelRecord + the parcel's current
design entities, so it always reflects the user's latest designs — no stale S3
cache. The ``scenario_engine`` dataclasses are the single source of truth.

ASSUMPTION (temporal scope): the pipeline computes EVENT-based runoff (SCS-CN
design storm); scenario_engine docstrings describe ANNUAL volumes. We feed the
pipeline's runoff volume as the reference volume — the comparison is still valid
as a RELATIVE baseline-vs-intervention assessment, surfaced via ``assumptions``.

ASSUMPTION (sediment retention): scales with the captured runoff fraction
(capturing water traps sediment). Documented, not fabricated.
"""
from __future__ import annotations

import logging

from nkz_platform_sdk import SyncOrionClient

from app.services.hydro_record import latest_hydro_record, num_attr
from app.services.scenario_engine import (
    simulate_baseline,
    simulate_intervention,
    compare_scenarios,
)

logger = logging.getLogger(__name__)

_DESIGN_TYPES = "nkz:WaterStorage,nkz:OpenChannelFlow"

_ASSUMPTIONS = (
    "Event-based runoff used as the reference volume (SCS-CN design storm); "
    "sediment retention scales with the captured runoff fraction."
)


def _aggregate_design_capture(designs: list[dict]) -> tuple[float, int]:
    """Sum water-capture capacity (m³) across the parcel's designs.

    Only designs carrying ``nkz:capacity`` (ponds) count — no capacity is
    invented for keylines/swales/check-dams (they channel water, not store it).
    """
    captured = 0.0
    count = 0
    for d in designs or []:
        cap = num_attr(d.get("nkz:capacity"))
        if cap and cap > 0:
            captured += cap
            count += 1
    return captured, count


def compute_scenarios(tenant_id: str, parcel_id: str) -> dict:
    """Compute baseline vs intervention scenarios on demand."""
    orion = SyncOrionClient(tenant_id)
    record = latest_hydro_record(orion, parcel_id)
    if not record:
        return {"status": "no_data"}

    area_ha = num_attr(record.get("nkz:parcelAreaHa")) or 0.0
    area_m2 = area_ha * 10_000.0
    runoff_mm = num_attr(record.get("nkz:runoffMm")) or 0.0
    sediment_t = num_attr(record.get("nkz:sedimentYieldTonnes")) or 0.0
    eto_mm = num_attr(record.get("nkz:etoMm")) or 0.0
    precip_mm = num_attr(record.get("nkz:precipitationMm")) or 0.0

    runoff_m3 = runoff_mm / 1000.0 * area_m2
    et_m3 = eto_mm / 1000.0 * area_m2
    precip_m3 = precip_mm / 1000.0 * area_m2

    baseline = simulate_baseline(runoff_m3, sediment_t, et_m3, precip_m3)

    try:
        designs = orion.query_entities(
            type=_DESIGN_TYPES,
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
        ) or []
    except Exception as exc:
        logger.warning("scenario designs query failed: %s", exc)
        designs = []

    captured_m3, designs_with_cap = _aggregate_design_capture(designs)
    capt_frac = min(1.0, captured_m3 / runoff_m3) if runoff_m3 > 0 else 0.0
    sediment_retained_t = sediment_t * capt_frac
    earthwork_m3 = captured_m3  # pond excavation ≈ stored volume

    intervention = simulate_intervention(
        baseline, captured_m3, sediment_retained_t, earthwork_m3,
    )

    return {
        "status": "ok",
        "baseline": vars(baseline),
        "intervention": vars(intervention),
        "comparison": compare_scenarios({"baseline": baseline, "intervention": intervention}),
        "designsConsidered": designs_with_cap,
        "capturedM3": round(captured_m3, 1),
        "assumptions": _ASSUMPTIONS,
    }
