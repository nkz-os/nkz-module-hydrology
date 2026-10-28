"""Per-parcel calculation settings (mode and design return period), kept in MinIO."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from botocore.exceptions import ClientError

from app.config import get_settings
from app.services.design_generator import _raster_key
from app.services.s3 import get_s3_client

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
DEFAULT_MODE = "storm"
DEFAULT_RETURN_PERIOD_YEARS = 10
ALLOWED_RETURN_PERIODS = (10, 25, 100)


@dataclass(frozen=True)
class ParcelSettings:
    mode: Literal["storm", "retention"]
    return_period_years: int
    is_default: bool
    updated_by: Optional[str]
    updated_at: Optional[str]


def _default() -> ParcelSettings:
    return ParcelSettings(DEFAULT_MODE, DEFAULT_RETURN_PERIOD_YEARS, True, None, None)


def load_settings(tenant_id: str, parcel_id: str) -> ParcelSettings:
    """Stored settings, or the defaults when none were saved. Other S3 errors propagate."""
    key = _raster_key(parcel_id, tenant_id, SETTINGS_FILE)
    try:
        resp = get_s3_client().get_object(Bucket=get_settings().minio_bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
            return _default()
        raise
    data = json.loads(resp["Body"].read())
    return ParcelSettings(
        mode=data["mode"],
        return_period_years=int(data["return_period_years"]),
        is_default=False,
        updated_by=data.get("updated_by"),
        updated_at=data.get("updated_at"),
    )


def save_settings(
    tenant_id: str, parcel_id: str, mode: str, return_period_years: int, user_id: str
) -> ParcelSettings:
    saved = ParcelSettings(
        mode=mode,
        return_period_years=return_period_years,
        is_default=False,
        updated_by=user_id,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    key = _raster_key(parcel_id, tenant_id, SETTINGS_FILE)
    body = json.dumps({
        "mode": saved.mode,
        "return_period_years": saved.return_period_years,
        "updated_by": saved.updated_by,
        "updated_at": saved.updated_at,
    }).encode()
    get_s3_client().put_object(
        Bucket=get_settings().minio_bucket, Key=key, Body=body, ContentType="application/json"
    )
    logger.info(
        "parcel settings saved tenant=%s parcel=%s mode=%s T=%s user=%s",
        tenant_id, parcel_id, mode, return_period_years, user_id,
    )
    return saved
