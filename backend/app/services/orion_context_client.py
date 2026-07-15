"""Orion-LD context client for soil and vegetation properties.

Fetches real CN, Ksat, field capacity, wilting point from AgriSoil and
latest NDVI from EOProduct. All queries soft-fail with platform defaults.

Uses SyncOrionClient.query_entities() — the canonical SDK method that
returns list[dict] directly, NOT a raw requests.Response.

Follows AGENTS §8: standard SDM context via Orion-LD broker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nkz_platform_sdk import SyncOrionClient

# Reuse the canonical CN table from the SCS-CN module instead of duplicating.
from app.services.scs_cn import HSG_CN_TABLE

logger = logging.getLogger(__name__)

# ── HSG derivation from USDA texture class ────────────────────────────
_HSG_TABLE: dict[str, str] = {
    "sand": "A",
    "loamy_sand": "A",
    "sandy_loam": "B",
    "loam": "B",
    "silt_loam": "B",
    "silt": "B",
    "sandy_clay_loam": "C",
    "clay_loam": "C",
    "silty_clay_loam": "C",
    "sandy_clay": "D",
    "silty_clay": "D",
    "clay": "D",
}

# K_factor baseline by broad texture class (Wischmeier-Smith)
_K_FACTOR_BASELINE: dict[str, float] = {
    "sand": 0.20, "loamy_sand": 0.25, "sandy_loam": 0.30,
    "loam": 0.32, "silt_loam": 0.38, "silt": 0.42,
    "sandy_clay_loam": 0.28, "clay_loam": 0.25, "silty_clay_loam": 0.30,
    "sandy_clay": 0.20, "silty_clay": 0.22, "clay": 0.17,
}


@dataclass
class SoilContext:
    cn: float = 80.0
    ksat_mmh: float = 15.0
    field_capacity_vv: float = 0.25
    wilting_point_vv: float = 0.10
    k_factor: float = 0.30
    source: str = "default"


def _derive_hsg(texture: str) -> str:
    """USDA texture class -> Hydrologic Soil Group."""
    key = texture.lower().replace(" ", "_").replace("-", "_")
    return _HSG_TABLE.get(key, "C")


def _hsg_to_cn(hsg: str, land_use: str = "row_crops") -> int:
    """HSG -> Curve Number (from HSG_CN_TABLE in scs_cn.py)."""
    return HSG_CN_TABLE.get((hsg, land_use), 85)


def _derive_k_factor(texture: str, organic_carbon_pct: float | None = None) -> float:
    """Estimate soil erodibility K factor from texture and organic matter."""
    key = texture.lower().replace(" ", "_").replace("-", "_")
    k = _K_FACTOR_BASELINE.get(key, 0.30)
    if organic_carbon_pct is not None:
        om_pct = organic_carbon_pct * 1.724  # van Bemmelen factor
        if om_pct > 2.0:
            k -= 0.05
    return round(max(0.10, min(0.50, k)), 2)


class OrionContextClient:
    """Fetches soil and vegetation context from Orion-LD.

    Uses SyncOrionClient.query_entities() — the canonical SDK method.
    All methods soft-fail: log warning, return defaults on any error.
    """

    def __init__(self, tenant_id: str):
        self._tenant = tenant_id
        self._orion: SyncOrionClient | None = None

    def __enter__(self) -> "OrionContextClient":
        self._orion = SyncOrionClient(self._tenant).__enter__()
        return self

    def __exit__(self, *_):
        if self._orion:
            self._orion.close()
        self._orion = None

    @property
    def orion(self) -> SyncOrionClient:
        if self._orion is None:
            self._orion = SyncOrionClient(self._tenant).__enter__()
        return self._orion

    # ── Soil ──────────────────────────────────────────────────────────

    def get_soil_context(self, parcel_id: str) -> SoilContext:
        """Query AgriSoil linked to parcel, extract top horizon properties.

        Uses query_entities(type="AgriSoil",
        q='(hasAgriParcel=="<id>"|refAgriParcel=="<id>")') — dual-relationship
        form covering both the new and legacy relationship names.
        Parses the first entity found.
        Returns SoilContext with source='orion' on success, 'default' on miss.
        """
        try:
            # Query both old (refAgriParcel) and new (hasAgriParcel) relationship
            # names per AGENTS §3 migration contract.
            entities = self.orion.query_entities(
                type="AgriSoil",
                q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")',
                options="keyValues",
            )
            if not entities:
                logger.info("No AgriSoil found for parcel %s", parcel_id)
                return SoilContext()
            return self._parse_soil_entity(entities[0])
        except Exception as exc:
            logger.warning("Orion query failed for AgriSoil: %s", exc)
            return SoilContext()

    def _parse_soil_entity(self, entity: dict[str, Any]) -> SoilContext:
        """Extract texture, Ksat, FC, WP, OC from a keyValues entity."""
        texture = entity.get("usdaTextureClass")
        ksat = entity.get("Ksaturation")
        fc = entity.get("fieldCapacity")
        wp = entity.get("wiltingPoint")
        oc = entity.get("organicCarbon")

        if not texture:
            logger.info("AgriSoil has no usdaTextureClass, using defaults")
            return SoilContext()

        hsg = _derive_hsg(str(texture))
        cn = float(_hsg_to_cn(hsg))
        ksat_val = float(ksat) if ksat is not None else 15.0
        fc_val = float(fc) if fc is not None else 0.25
        wp_val = float(wp) if wp is not None else 0.10
        oc_val = float(oc) if oc is not None else None
        kf = _derive_k_factor(str(texture), oc_val)

        return SoilContext(
            cn=cn, ksat_mmh=ksat_val, field_capacity_vv=fc_val,
            wilting_point_vv=wp_val, k_factor=kf, source="orion",
        )

    # ── Vegetation ─────────────────────────────────────────────────────

    def get_ndvi_mean(self, parcel_id: str) -> tuple[float, str]:
        """Query latest EOProduct with indexType=NDVI.

        Uses query_entities with type="EOProduct" and a compound q filter.
        Sorts by dateObserved descending, takes the first entity.
        Returns (ndvi_mean, source) where source is 'orion' or 'default'.
        """
        try:
            # Query both old (refAgriParcel) and new (hasAgriParcel) relationship
            # names per AGENTS §3 migration contract.
            entities = self.orion.query_entities(
                type="EOProduct",
                q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");indexType=="NDVI"',
                options="keyValues",
            )
            if not entities:
                logger.info("No EOProduct found for parcel %s", parcel_id)
                return (0.4, "default")

            def _parse_date(e: dict) -> str:
                d = e.get("dateObserved")
                if isinstance(d, dict):
                    d = d.get("@value", "") if isinstance(d.get("@value"), str) else d.get("value", "")
                return str(d or "")

            entities.sort(key=_parse_date, reverse=True)
            mean_val = entities[0].get("meanValue")
            if mean_val is None:
                return (0.4, "default")
            return (float(mean_val), "orion")
        except Exception as exc:
            logger.warning("Orion query failed for EOProduct: %s", exc)
            return (0.4, "default")
