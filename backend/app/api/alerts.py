"""Hydrologic alert endpoint (on-demand, Phase 2A — reactive)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from nkz_platform_sdk import AuthContext

from app.middleware import require_auth
from app.services.alerts_compute import compute_alerts

router = APIRouter(prefix="/parcels", tags=["hydrology-alerts"])


@router.get("/{parcel_id}/alerts")
def get_parcel_alerts(
    parcel_id: str,
    auth: AuthContext = require_auth(),
) -> dict:
    """Active saturation-excess / infiltration-excess alerts for a parcel."""
    return compute_alerts(auth.tenant_id, parcel_id)
