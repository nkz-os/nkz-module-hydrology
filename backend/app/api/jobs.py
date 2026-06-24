"""Job status polling. Sanitizes RQ exc_info — never returns tracebacks to clients."""
from fastapi import APIRouter, HTTPException, Depends
from redis import Redis
from rq.job import Job as RQJob

from app.config import get_settings
from app.middleware import require_auth
from nkz_platform_sdk import AuthContext

router = APIRouter(prefix="/jobs", tags=["Job Management"])


@router.get("/{job_id}")
async def get_job_status(job_id: str, ctx: AuthContext = require_auth()):
    """Get the status and result of a background job."""
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)

    try:
        job = RQJob.fetch(job_id, connection=redis)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    result = {
        "job_id": job_id,
        "status": job.get_status(),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }
    if job.is_failed:
        # exc_info contains full Python tracebacks — internal only.
        result["error"] = "job failed"
    elif job.is_finished:
        result["result"] = job.result
    return result
