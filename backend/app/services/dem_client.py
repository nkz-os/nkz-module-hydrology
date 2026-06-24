"""DEM client for hydrology: fetches a DEM grid from eu-elevation.

Service-to-service (namespace `nekazari`), NO auth: eu-elevation's /raster is
public (verified 2026-06-24). X-Tenant-ID is sent for observability only.
When eu-elevation is hardened (see PENDING.md), add HMAC here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_AREA_THRESHOLD_HA = 10.0     # < 10 ha -> 5m, >= 10 ha -> 25m (owner decision)
_RES_SMALL = 5.0
_RES_LARGE = 25.0


class DEMUnavailable(Exception):
    """eu-elevation could not serve a DEM for the bbox (no coverage / unreachable)."""


@dataclass
class DEMGrid:
    elevations: list[list[float]]
    origin_lon: float
    origin_lat: float
    pixel_size_deg: float
    cols: int
    rows: int
    source: dict[str, Any]


def resolution_for_area_ha(area_ha: float) -> float:
    """Pick DEM resolution by parcel area (5m for small, 25m for large)."""
    return _RES_SMALL if area_ha < _AREA_THRESHOLD_HA else _RES_LARGE


class DEMClient:
    """Thin client for eu-elevation's GET /api/elevation/raster."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or get_settings().eu_elevation_url).rstrip("/")
        self.timeout = timeout

    def fetch_dem(
        self,
        bbox_wgs84: tuple[float, float, float, float],
        resolution_m: float,
        tenant_id: str | None = None,
    ) -> DEMGrid:
        min_lon, min_lat, max_lon, max_lat = bbox_wgs84
        params = {
            "min_lon": min_lon, "min_lat": min_lat,
            "max_lon": max_lon, "max_lat": max_lat,
            "resolution_m": resolution_m,
        }
        headers = {"X-Tenant-ID": tenant_id} if tenant_id else {}
        try:
            resp = httpx.get(
                f"{self.base_url}/api/elevation/raster",
                params=params, headers=headers, timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise DEMUnavailable(f"eu-elevation unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise DEMUnavailable(f"eu-elevation {resp.status_code}: {resp.text[:200]}")
        d = resp.json()
        return DEMGrid(
            elevations=d["elevations"],
            origin_lon=d["origin_lon"], origin_lat=d["origin_lat"],
            pixel_size_deg=d["pixel_size_deg"], cols=d["cols"], rows=d["rows"],
            source=d.get("source", {}),
        )
