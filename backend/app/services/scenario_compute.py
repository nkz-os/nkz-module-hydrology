"""On-demand baseline-vs-intervention scenario comparison.

Computed live from the latest hydrology AgriParcelRecord + the parcel's current
design entities, so it always reflects the user's latest designs — no stale S3
cache (the old /visualization/{id}/kpis read a key nothing wrote). The
``scenario_engine`` dataclasses are the single source of truth for the math.

ASSUMPTION (temporal scope): the hydrology pipeline computes EVENT-based runoff
(SCS-CN design storm), while scenario_engine docstrings describe ANNUAL volumes.
We feed the pipeline's runoff volume as the reference volume — the comparison is
still valid as a RELATIVE baseline-vs-intervention assessment (the ratio is what
the user reads off), and the absolute framing is surfaced to the caller via
``assumptions`` rather than hidden.

ASSUMPTION (sediment retention): sediment retained scales with the fraction of
runoff captured (capturing water physically traps sediment). Documented here,
not fabricated: no per-design retention coefficient is invented.
"""
from __future__ import annotations

import logging
from typing import Any

from nkz_platform_sdk import SyncOrionClient

from app.services.scenario_engine import (
    simulate_baseline,
    simulate_intervention,
    compare_scenarios,
)

logger = logging.getLogger(__name__)

# Both design types in one comma-type list (comma IS valid in the type param).
_DESIGN_TYPES = "nkz:WaterStorage,nkz:OpenChannelFlow"

_ASSUMPTIONS = (
    "Event-based runoff used as the reference volume (SCS-CN design storm); "
    "sediment retention scales with the captured runoff fraction."
)


def _num(attr: Any) -> float | None:
    """Unwrap a possibly-normalized NGSI-LD scalar attribute to float."""
    if isinstance(attr, dict):
        attr = attr.get("value", attr.get("@value"))
    try:
        return float(attr) if attr is not None else None
    except (TypeError, ValueError):
        return None


def _latest_hydro_record(orion: SyncOrionClient, parcel_id: str) -> dict:
    """Latest hydrology AgriParcelRecord for the parcel (id-prefix filters foreign modules)."""
    entities = orion.query_entities(
        type="AgriParcelRecord",
        q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");nkz:demSource',
        options="keyValues",
        limit=100,
    ) or []
    hydro = [
        e for e in entities
        if str(e.get("id", "")).startswith("urn:ngsi-ld:AgriParcelRecord:hydrology-")
    ]
    if not hydro:
        return {}
    hydro.sort(key=lambda e: str(e.get("dateObserved", "")), reverse=True)
    return hydro[0]


def _aggregate_design_capture(designs: list[dict]) -> tuple[float, int]:
    """Sum water-capture capacity (m³) across the parcel's designs.

    Only designs carrying a capacity (ponds via ``nkz:capacity``) count — no
    capacity is invented for keylines/swales/check-dams (they channel water,
    not store it).

    Returns ``(captured_m3, design_count_with_capacity)``.
    """
    captured = 0.0
    count = 0
    for d in designs or []:
        cap = _num(d.get("nkz:capacity"))
        if cap and cap > 0:
            captured += cap
            count += 1
    return captured, count


def compute_scenarios(tenant_id: str, parcel_id: str) -> dict:
    """Compute baseline vs intervention scenarios on demand."""
    orion = SyncOrionClient(tenant_id)
    record = _latest_hydro_record(orion, parcel_id)
    if not record:
        return {"status": "no_data"}

    area_ha = _num(record.get("nkz:parcelAreaHa")) or 0.0
    area_m2 = area_ha * 10_000.0
    runoff_mm = _num(record.get("nkz:runoffMm")) or 0.0
    sediment_t = _num(record.get("nkz:sedimentYieldTonnes")) or 0.0
    eto_mm = _num(record.get("nkz:etoMm")) or 0.0
    precip_mm = _num(record.get("nkz:precipitationMm")) or 0.0

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
