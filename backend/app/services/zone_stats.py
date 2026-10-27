"""TWI statistics for arbitrary zone geometries (built by other modules).

Zone geometries arrive as EPSG:4326 GeoJSON; the parcel rasters are stored in
UTM. Each zone is reprojected to the raster CRS and masked. A zone covering
fewer than MIN_ZONE_PIXELS valid pixels reports the parcel-wide values with
fidelity ``parcel_inherited`` instead of fabricating a zone value.
"""
from __future__ import annotations

import io
from typing import Any, Optional

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

MIN_ZONE_PIXELS = 20
_WGS84 = "EPSG:4326"


def read_raster(data: bytes) -> tuple[np.ndarray, Any, Any]:
    """Read band 1 as float32 with nodata/non-finite set to NaN."""
    with rasterio.open(io.BytesIO(data)) as src:
        arr = src.read(1).astype("float32")
        if src.nodata is not None:
            arr[arr == np.float32(src.nodata)] = np.nan
        return arr, src.transform, src.crs


def parcel_p80(twi: np.ndarray) -> float:
    """80th percentile of valid TWI (the twi-high / twi-very-high threshold)."""
    valid = twi[np.isfinite(twi)]
    if valid.size == 0:
        raise ValueError("TWI raster has no valid pixels")
    return float(np.percentile(valid, 80))


def _stats(twi, slope, accum, sel, p80) -> dict:
    t = twi[sel]
    out: dict[str, Optional[float]] = {
        "twiMean": float(np.mean(t)),
        "twiP90": float(np.percentile(t, 90)),
        "wetFraction": float(np.mean(t >= p80)),
        "slopeMean": None,
        "flowAccumMax": None,
    }
    if slope is not None:
        s = slope[sel]
        s = s[np.isfinite(s)]
        if s.size:
            out["slopeMean"] = float(np.mean(s))
    if accum is not None:
        a = accum[sel]
        a = a[np.isfinite(a)]
        if a.size:
            out["flowAccumMax"] = float(np.max(a))
    return out


def zone_stats(
    twi: np.ndarray,
    slope: Optional[np.ndarray],
    accum: Optional[np.ndarray],
    transform,
    crs,
    zones: list[dict],
    parcel_p80: float,
) -> list[dict]:
    """Per-zone statistics; zones are ``{zoneId, zoneVersion, geometry}``."""
    valid = np.isfinite(twi)
    for other in (slope, accum):
        if other is not None and other.shape != twi.shape:
            raise ValueError("raster grids differ in shape")
    parcel = _stats(twi, slope, accum, valid, parcel_p80)

    results = []
    for z in zones:
        geom = transform_geom(_WGS84, crs, z["geometry"])
        inside = geometry_mask([geom], out_shape=twi.shape, transform=transform, invert=True)
        sel = inside & valid
        if int(sel.sum()) >= MIN_ZONE_PIXELS:
            vals, fidelity = _stats(twi, slope, accum, sel, parcel_p80), "zone_specific"
        else:
            vals, fidelity = dict(parcel), "parcel_inherited"
        results.append(
            {
                "zoneId": z["zoneId"],
                "zoneVersion": z.get("zoneVersion"),
                **vals,
                "fidelity": fidelity,
            }
        )
    return results
