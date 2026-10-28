"""Per-parcel calculation settings endpoints."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter
from nkz_platform_sdk import AuthContext
from pydantic import BaseModel, field_validator

from app.middleware import require_auth
from app.services import parcel_settings

router = APIRouter(prefix="/parcels", tags=["hydrology-settings"])

_WRITE_ROLES = ["TechnicalConsultant", "TenantAdmin", "PlatformAdmin"]


class SettingsBody(BaseModel):
    mode: Literal["storm", "retention"]
    return_period_years: int

    @field_validator("return_period_years")
    @classmethod
    def _period(cls, v: int) -> int:
        if v not in parcel_settings.ALLOWED_RETURN_PERIODS:
            raise ValueError(f"return_period_years must be one of {parcel_settings.ALLOWED_RETURN_PERIODS}")
        return v


@router.get("/{parcel_id}/settings")
def get_parcel_settings(parcel_id: str, auth: AuthContext = require_auth()):
    return asdict(parcel_settings.load_settings(auth.tenant_id, parcel_id))


@router.put("/{parcel_id}/settings")
def put_parcel_settings(
    parcel_id: str, body: SettingsBody, auth: AuthContext = require_auth(roles=_WRITE_ROLES)
):
    saved = parcel_settings.save_settings(
        auth.tenant_id, parcel_id, body.mode, body.return_period_years, auth.user_id
    )
    return asdict(saved)
