"""Tests for /jobs/{job_id} — tenant ownership scoping (no cross-tenant reads)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _job(args, status="finished"):
    job = MagicMock()
    job.args = args
    job.get_status.return_value = status
    job.created_at = None
    job.ended_at = None
    job.is_failed = False
    job.is_finished = status == "finished"
    job.result = {"ok": True}
    return job


@pytest.mark.asyncio
async def test_job_owner_can_read():
    """A job whose args[2] tenant matches the caller is returned."""
    from app.api.jobs import get_job_status

    job = _job(("urn:p1", "job-1", "tenant-a"))
    with patch("app.api.jobs.get_settings", lambda: SimpleNamespace(redis_url="redis://x")), \
         patch("app.api.jobs.Redis"), \
         patch("app.api.jobs.RQJob.fetch", return_value=job):
        result = await get_job_status("job-1", ctx=SimpleNamespace(tenant_id="tenant-a"))

    assert result["job_id"] == "job-1"
    assert result["status"] == "finished"


@pytest.mark.asyncio
async def test_job_tenant_mismatch_returns_404():
    """A job owned by another tenant returns 404 (same body as not-found)."""
    from fastapi import HTTPException
    from app.api.jobs import get_job_status

    job = _job(("urn:p1", "job-1", "tenant-b"))
    with patch("app.api.jobs.get_settings", lambda: SimpleNamespace(redis_url="redis://x")), \
         patch("app.api.jobs.Redis"), \
         patch("app.api.jobs.RQJob.fetch", return_value=job):
        with pytest.raises(HTTPException) as exc:
            await get_job_status("job-1", ctx=SimpleNamespace(tenant_id="tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Job not found"


@pytest.mark.asyncio
async def test_job_missing_args_returns_404():
    """A job with too few args (no tenant slot) returns 404 — no info leak."""
    from fastapi import HTTPException
    from app.api.jobs import get_job_status

    job = _job(("urn:p1",))
    with patch("app.api.jobs.get_settings", lambda: SimpleNamespace(redis_url="redis://x")), \
         patch("app.api.jobs.Redis"), \
         patch("app.api.jobs.RQJob.fetch", return_value=job):
        with pytest.raises(HTTPException) as exc:
            await get_job_status("job-1", ctx=SimpleNamespace(tenant_id="tenant-a"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Job not found"
