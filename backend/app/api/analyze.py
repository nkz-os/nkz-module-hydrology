"""
NKZ Water Studio — Hydrology Analysis Router

Enqueues DEM pipeline jobs via RQ. Returns 202 with job_id.
Tenant-scoped: the authenticated tenant is propagated to the worker.
"""

import uuid
from fastapi import APIRouter, Depends
from redis import Redis
from rq import Queue

from app.config import get_settings
from app.middleware import require_auth
from nkz_platform_sdk import AuthContext

router = APIRouter(prefix="/analyze", tags=["Hydrology Analysis"])


@router.post("/{parcel_id}", status_code=202)
async def analyze_parcel(parcel_id: str, ctx: AuthContext = require_auth()):
    """Enqueue a DEM pipeline job for the given parcel (tenant-scoped)."""
    from app.workers.hydrology_worker import run_dem_pipeline

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    queue = Queue("hydrology-processing", connection=redis)

    job_id = str(uuid.uuid4())
    # Pass tenant_id so the worker operates in the correct tenant context.
    queue.enqueue(
        run_dem_pipeline,
        args=(parcel_id, job_id, ctx.tenant_id),
        job_id=job_id,
        job_timeout=settings.worker_timeout,
        result_ttl=86400,
    )
    return {"job_id": job_id, "status": "queued", "parcel_id": parcel_id, "tenant_id": ctx.tenant_id}
