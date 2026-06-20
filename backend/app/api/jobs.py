"""
NKZ Water Studio — Job Management Router

Polls RQ job status for hydrology analysis jobs.
"""

from fastapi import APIRouter, HTTPException
from redis import Redis
from rq.job import Job as RQJob
from app.config import get_settings

router = APIRouter(prefix="/jobs", tags=["Job Management"])


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    """Get the status and result of a background job."""
    _settings = get_settings()
    _redis = Redis.from_url(_settings.redis_url)

    try:
        job = RQJob.fetch(job_id, connection=_redis)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job_id,
        "status": job.get_status(),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }
    if job.is_failed:
        result["error"] = str(job.exc_info)
    elif job.is_finished:
        result["result"] = job.result
    return result
