"""
NKZ Water Studio — Job Management Router

Background job lifecycle via RQ (Redis Queue).
"""

from fastapi import APIRouter, Depends

from app.middleware import TokenPayload, get_current_user, get_tenant_id

router = APIRouter(prefix="/jobs", tags=["Job Management"])


@router.get("/health")
async def jobs_health():
    """Jobs sub-router health check."""
    return {"status": "jobs_ok"}


@router.get("/")
async def list_jobs(
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """List background jobs for the current tenant."""
    return {"jobs": [], "message": "list endpoint — not yet implemented"}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    tenant_id: str = Depends(get_tenant_id),
    user: TokenPayload = Depends(get_current_user),
):
    """Get a single job's status and result."""
    return {"job_id": job_id, "status": "pending", "message": "not yet implemented"}
