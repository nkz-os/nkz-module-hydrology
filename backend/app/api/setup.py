"""
NKZ Water Studio — Module Setup Router

Parcel activation / deactivation lifecycle.
Called by entity-manager via internal-service-secret auth.
"""

from fastapi import APIRouter, Depends

from app.middleware import TokenPayload, get_current_user, get_tenant_id

router = APIRouter(prefix="/setup", tags=["Module Setup"])


@router.get("/health")
async def setup_health():
    """Setup sub-router health check."""
    return {"status": "setup_ok"}


@router.post("/parcel/{parcel_id}")
async def setup_parcel(
    parcel_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Activate hydrology for a parcel.
    Called by entity-manager during module activation lifecycle.
    """
    return {
        "parcel_id": parcel_id,
        "status": "ok",
        "message": "setup endpoint — not yet implemented",
    }


@router.delete("/parcel/{parcel_id}")
async def teardown_parcel(
    parcel_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Deactivate hydrology for a parcel.
    Called by entity-manager during module deactivation lifecycle.
    """
    return {
        "parcel_id": parcel_id,
        "status": "ok",
        "message": "teardown endpoint — not yet implemented",
    }
