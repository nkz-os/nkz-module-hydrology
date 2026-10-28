"""Cache of the history-derived design figures, one JSON document per parcel in MinIO.

The key is mode + return period + last full year of the history: a new year of
data or a changed setting recomputes, anything else is a hit and skips the
30-year history fetch. A cache that cannot be read or written never blocks the
job: it falls back to computing.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from botocore.exceptions import ClientError

from app.config import get_settings
from app.services.s3 import get_s3_client
from app.services.tile_service import parcel_short

logger = logging.getLogger(__name__)

CACHE_FILE = "design_cache.json"


def _key(tenant_id: str, parcel_id: str) -> str:
    return f"hydrology/{tenant_id}/{parcel_short(parcel_id)}/{CACHE_FILE}"


def get_or_compute(
    tenant_id: str,
    parcel_id: str,
    mode: str,
    return_period_years: int,
    last_full_year: int,
    compute: Callable[[], dict],
) -> dict:
    """Cached value for the key, or ``compute()`` stored under it."""
    cache_key = {"mode": mode, "return_period_years": int(return_period_years),
                 "last_full_year": int(last_full_year)}
    s3_key = _key(tenant_id, parcel_id)
    bucket = get_settings().minio_bucket
    try:
        s3 = get_s3_client()
        doc = json.loads(s3.get_object(Bucket=bucket, Key=s3_key)["Body"].read())
        if doc.get("key") == cache_key and isinstance(doc.get("value"), dict):
            logger.info("design cache hit tenant=%s parcel=%s key=%s", tenant_id, parcel_id, cache_key)
            return doc["value"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404", "NotFound"):
            logger.warning("design cache read failed tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)
    except Exception as exc:  # unreadable or corrupt cache: recompute
        logger.warning("design cache unusable tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)

    value = compute()
    try:
        get_s3_client().put_object(
            Bucket=bucket, Key=s3_key,
            Body=json.dumps({"key": cache_key, "value": value}).encode(),
            ContentType="application/json",
        )
    except Exception as exc:
        logger.warning("design cache write failed tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)
    return value


def invalidate(tenant_id: str, parcel_id: str) -> None:
    """Remove the parcel's cache document (best effort)."""
    try:
        get_s3_client().delete_object(Bucket=get_settings().minio_bucket, Key=_key(tenant_id, parcel_id))
    except Exception as exc:
        logger.warning("design cache invalidate failed tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)
