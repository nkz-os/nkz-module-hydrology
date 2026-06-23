"""
NKZ Water Studio — Hydrology Analysis Router

Enqueues DEM pipeline jobs via RQ. Returns 202 with job_id.
"""

import uuid
from fastapi import APIRouter
from redis import Redis
from rq import Queue

from app.config import get_settings

router = APIRouter(prefix="/analyze", tags=["Hydrology Analysis"])


@router.post("/{parcel_id}", status_code=202)
async def analyze_parcel(parcel_id: str):
    """Enqueue a DEM pipeline job for the given parcel."""
    from app.workers.hydrology_worker import run_dem_pipeline

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    queue = Queue("hydrology-processing", connection=redis)

    job_id = str(uuid.uuid4())
    queue.enqueue(
        run_dem_pipeline,
        args=(parcel_id, job_id),
        job_id=job_id,
        job_timeout=settings.worker_timeout,
        result_ttl=86400,
    )
    return {"job_id": job_id, "status": "queued", "parcel_id": parcel_id}
