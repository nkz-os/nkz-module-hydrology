"""RQ entry point: keyline layout in the background.

The synchronous endpoint stops the layout at a short time budget so the
request fits under the gateway timeout; in the worker the layout gets a
longer one and the UI polls `/jobs/{job_id}` for the result.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Seconds the layout may run in the worker (well under `worker_timeout`).
JOB_TIME_BUDGET_S = 120.0


def run_keyline_job(parcel_id: str, job_id: str, tenant_id: str, params: dict) -> dict:
    """Same response as `POST /design/keyline/generate`.

    A broker failure comes back as its status dict (`orion_unavailable`) so
    the UI can say why, instead of a bare failed job.
    """
    from app.api.designs import KeylineRequest, compute_keyline

    logger.info("[%s] keyline job parcel=%s tenant=%s", job_id, parcel_id, tenant_id)
    req = KeylineRequest(**{**params, "parcel_id": parcel_id})
    try:
        return compute_keyline(req, tenant_id, time_budget_s=JOB_TIME_BUDGET_S)
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and "status" in exc.detail:
            return dict(exc.detail)
        raise
