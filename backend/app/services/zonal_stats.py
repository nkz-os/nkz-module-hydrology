"""Zonal statistics extractor for TWI zones.

Computes per-zone mean slope, TWI, and area from GeoLibre output rasters
by masking each zone's TWI range on the raster arrays.
"""
from __future__ import annotations

import io
import re

import numpy as np
import rasterio


def _read_raster(tif_bytes: bytes) -> np.ndarray:
    with rasterio.open(io.BytesIO(tif_bytes)) as ds:
        return ds.read(1)


def _pixel_area_ha(transform: rasterio.Affine, count: int) -> float:
    return abs(transform.a * transform.e) / 10000.0 * count


def _parse_twi_range(twi_range: str) -> tuple[float, float]:
    """Robustly parse TWI range strings like '-inf-6.0', '6.0-10.0', '26.0-inf'.

    Uses regex to handle the '-inf' prefix and 'inf' suffix correctly,
    avoiding the bug where a naive split on '-' would break on '-inf'.
    """
    m = re.match(
        r"^(-inf|[\d.]+)\s*-\s*([\d.]+|inf)$",
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
    accum_bytes: bytes,
) -> list[dict]:
    """Enrich each zone dict with zonal mean stats.

    Adds to each zone dict: slopeMean (float, percent), areaHa (float),
    pixelCount (int, updated from raster). Zones without matching pixels
    keep their existing values.

    Args:
        zones: List from _compute_zones, each with zone_id, twiRange.
        slope_bytes: GeoLibre slope GeoTIFF (bytes).
        twi_bytes: GeoLibre TWI GeoTIFF (bytes).
        accum_bytes: GeoLibre flow accumulation GeoTIFF (bytes) — reserved
            for future use.

    Returns:
        Zones list with added keys (mutates in place).
    """
    if not zones:
        return zones

    slope_arr = _read_raster(slope_bytes)
    twi_arr = _read_raster(twi_bytes)

    twi_flat = twi_arr.ravel()
    slope_flat = slope_arr.ravel()

    with rasterio.open(io.BytesIO(slope_bytes)) as ds:
        transform = ds.transform

    for zone in zones:
        lo, hi = _parse_twi_range(zone.get("twiRange", "-inf-inf"))
        mask = (twi_flat > lo) & (twi_flat <= hi)
        count = int(mask.sum())
        if count == 0:
            continue
        zone["slopeMean"] = float(np.nanmean(slope_flat[mask]))
        zone["areaHa"] = round(_pixel_area_ha(transform, count), 4)
        zone["pixelCount"] = count

    return zones
