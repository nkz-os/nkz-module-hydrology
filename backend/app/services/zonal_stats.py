"""Zonal statistics extractor for TWI zones.

Computes per-zone mean slope, and area from GeoLibre output rasters
by masking each zone's TWI range on the raster arrays.

TWI range format comes from ``_compute_zones`` in ``hydrology_worker.py``
(e.g. ``-inf-6.0``, ``6.0-10.0``, ``26.0-inf``).
"""
from __future__ import annotations

import io
import re
from typing import Optional

import numpy as np
import rasterio


def _pixel_area_ha(transform: rasterio.Affine, count: int) -> float:
    return abs(transform.a * transform.e) / 10000.0 * count


def _parse_twi_range(twi_range: str) -> tuple[float, float]:
    """Robustly parse TWI range strings like '-inf-6.0', '6.0-10.0', '26.0-inf'.

    Uses regex to handle the '-inf' prefix and 'inf' suffix correctly,
    avoiding the bug where a naive split on '-' would break on '-inf'.
    """
    m = re.match(
        r"^(-inf|-?[\d.]+)\s*-\s*(-?[\d.]+|inf)$",
        twi_range.strip(),
    )
    if not m:
        raise ValueError(f"Invalid TWI range format: {twi_range!r}")
    lo_str, hi_str = m.group(1), m.group(2)
    lo = -np.inf if lo_str == "-inf" else float(lo_str)
    hi = np.inf if hi_str == "inf" else float(hi_str)
    return lo, hi


def extract_zonal_stats(
    zones: list[dict],
    slope_bytes: bytes,
    twi_bytes: bytes,
    accum_bytes: Optional[bytes] = None,
) -> list[dict]:
    """Enrich each zone dict with zonal mean stats.

    Adds to each zone dict: slopeMean (float, degrees), areaHa (float),
    pixelCount (int, updated from raster). Zones without matching pixels
    keep their existing values.

    Args:
        zones: List from _compute_zones, each with zone_id, twiRange.
        slope_bytes: GeoLibre slope GeoTIFF (bytes).
        twi_bytes: GeoLibre TWI GeoTIFF (bytes).
        accum_bytes: GeoLibre flow accumulation GeoTIFF (bytes), optional.
            Reserved for future use (zonal flow accumulation).

    Returns:
        Zones list with added keys (mutates in place).
    """
    if not zones:
        return zones

    with rasterio.open(io.BytesIO(twi_bytes)) as ds:
        twi_arr = ds.read(1)
        twi_nodata = ds.nodata
    with rasterio.open(io.BytesIO(slope_bytes)) as ds:
        slope_arr = ds.read(1)
        slope_nodata = ds.nodata
        transform = ds.transform

    twi_flat = twi_arr.ravel()
    slope_flat = slope_arr.ravel()

    valid = np.isfinite(twi_flat)
    if twi_nodata is not None:
        valid &= twi_flat != twi_nodata

    for zone in zones:
        lo, hi = _parse_twi_range(zone.get("twiRange", "-inf-inf"))
        mask = valid & (twi_flat > lo) & (twi_flat <= hi)
        count = int(mask.sum())
        if count == 0:
            continue
        slope_vals = slope_flat[mask].astype(float)
        if slope_nodata is not None:
            slope_vals = slope_vals[slope_vals != slope_nodata]
        if slope_vals.size == 0:
            continue
        zone["slopeMean"] = float(np.nanmean(slope_vals))
        zone["areaHa"] = round(_pixel_area_ha(transform, count), 4)
        zone["pixelCount"] = count

    return zones
