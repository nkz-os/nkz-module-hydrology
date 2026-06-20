"""
NKZ Water Studio — Hydrology Analysis Router

Endpoints for watershed, flow accumulation, and DEM-based analysis.
"""

from fastapi import APIRouter, Depends

from app.middleware import TokenPayload, get_current_user, get_tenant_id

router = APIRouter(prefix="/analyze", tags=["Hydrology Analysis"])


@router.get("/health")
async def analyze_health():
    """Analyze sub-router health check."""
    return {"status": "analyze_ok"}


@router.post("/watershed")
async def compute_watershed(
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """Compute watershed boundaries for a given parcel or point."""
    return {"message": "watershed endpoint — not yet implemented"}


@router.post("/flow-accumulation")
async def compute_flow_accumulation(
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """Compute flow accumulation raster from DEM."""
    return {"message": "flow-accumulation endpoint — not yet implemented"}
