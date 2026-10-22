"""Hydrology scenario comparison endpoint (on-demand baseline vs intervention)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from nkz_platform_sdk import AuthContext

from app.middleware import require_auth
from app.services.scenario_compute import compute_scenarios

router = APIRouter(prefix="/parcels", tags=["hydrology-scenarios"])


@router.get("/{parcel_id}/scenarios")
def get_parcel_scenarios(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Baseline vs intervention KPIs, computed from the latest record + designs."""
    return compute_scenarios(auth.tenant_id, parcel_id)
