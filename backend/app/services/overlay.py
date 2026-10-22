"""NKZ Water Studio — TWI PNG overlay service.

Renders the per-parcel TWI GeoTIFF (UTM) into a colorized RGBA PNG plus a
WGS84 lon/lat bounds envelope, both cached in the tenant-scoped MinIO bucket.

Why a PNG (not the PMTiles path): a lightweight ground-overlay image the map
can drape over a parcel with 4 corner bounds — no tile server needed. The
endpoint returns JSON only (presigned PNG URL + bounds); the browser fetches
the PNG straight from the private bucket. The api-gateway 502s any non-JSON
response, so the module must never serve the image bytes itself.

Keys (tenant-scoped, hermeticity): hydrology/{tenant}/{parcel_short}/
  - twi_overlay.png
  - twi_overlay_bounds.json
"""
from __future__ import annotations

import io
import json
import logging
from typing import Optional

import numpy as np

from app.config import get_settings
from app.services.tile_service import parcel_short

logger = logging.getLogger(__name__)

# Alpha for valid (non-nodata) pixels: ~70% opacity so basemap shows through.
_ALPHA = 178

# Viridis anchors (RGB 0-255) at 9 evenly spaced stops. Interpolated to a
# 256-entry LUT below — faithful to matplotlib viridis without pulling in
# matplotlib (HPND/BSD-clean, no heavy dep).
_VIRIDIS_ANCHORS = np.array(
    [
        [68, 1, 84],
        [72, 40, 120],
        [62, 74, 137],
        [49, 104, 142],
        [38, 130, 142],
        [31, 158, 137],
        [53, 183, 121],
        [110, 206, 88],
        [253, 231, 37],
    ],
    dtype=np.float64,
)


def _viridis_lut() -> np.ndarray:
    """Build a 256x3 uint8 viridis LUT by interpolating the anchor stops."""
    n = _VIRIDIS_ANCHORS.shape[0]
    xp = np.linspace(0.0, 255.0, n)
    x = np.arange(256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for c in range(3):
        lut[:, c] = np.interp(x, xp, _VIRIDIS_ANCHORS[:, c]).round().astype(np.uint8)
    return lut


_LUT = _viridis_lut()


def _s3_client():
    from app.services.s3 import get_s3_client
    return get_s3_client()


def overlay_png_key(parcel_id: str, tenant_id: str) -> str:
    """Tenant-scoped MinIO key for the TWI overlay PNG."""
    return f"hydrology/{tenant_id}/{parcel_short(parcel_id)}/twi_overlay.png"


def overlay_bounds_key(parcel_id: str, tenant_id: str) -> str:
    """Tenant-scoped MinIO key for the sibling WGS84 bounds JSON."""
    return f"hydrology/{tenant_id}/{parcel_short(parcel_id)}/twi_overlay_bounds.json"


def render_twi_overlay(tif_bytes: bytes) -> tuple[bytes, dict]:
    """Render a UTM TWI GeoTIFF into an RGBA PNG + WGS84 bounds.

    Returns:
        (png_bytes, bounds) where bounds = {west, south, east, north} in degrees.
    """
    import rasterio
    from pyproj import Transformer
    from PIL import Image

    with rasterio.open(io.BytesIO(tif_bytes)) as ds:
        band = ds.read(1).astype(np.float64)
        nodata = ds.nodata
        left, bottom, right, top = ds.bounds
        src_crs = ds.crs

    # Mask nodata and non-finite (±inf, NaN) cells.
    invalid = ~np.isfinite(band)
    if nodata is not None:
        invalid |= band == nodata
    valid = ~invalid

    # Normalize the valid range on the 2nd–98th percentile for contrast.
    rgb = np.zeros((*band.shape, 3), dtype=np.uint8)
    if valid.any():
        vals = band[valid]
        lo, hi = np.percentile(vals, 2), np.percentile(vals, 98)
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
        idx = (norm * 255.0).round().astype(np.uint8)
        rgb = _LUT[idx]

    alpha = np.where(valid, _ALPHA, 0).astype(np.uint8)
    rgba = np.dstack([rgb, alpha]).astype(np.uint8)

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")

    # Bounds: transform all 4 corners UTM->WGS84 and take min/max. A projected
    # rectangle's edges bow, so the corner envelope is the correct WGS84 bbox.
    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    xs = [left, right, right, left]
    ys = [bottom, bottom, top, top]
    lons, lats = transformer.transform(xs, ys)
    bounds = {
        "west": float(min(lons)),
        "south": float(min(lats)),
        "east": float(max(lons)),
        "north": float(max(lats)),
    }
    return buf.getvalue(), bounds


def _load_cached_bounds(s3, bucket: str, parcel_id: str, tenant_id: str) -> Optional[dict]:
    """Return cached bounds if BOTH the PNG and bounds JSON exist, else None."""
    png_key = overlay_png_key(parcel_id, tenant_id)
    bounds_key = overlay_bounds_key(parcel_id, tenant_id)
    try:
        s3.head_object(Bucket=bucket, Key=png_key)
        resp = s3.get_object(Bucket=bucket, Key=bounds_key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return None


def ensure_twi_overlay(parcel_id: str, tenant_id: str) -> Optional[dict]:
    """Ensure the TWI overlay PNG + bounds exist in MinIO for a parcel.

    Cache-first: if both objects already exist, returns the cached bounds
    without re-rendering. Otherwise downloads twi.tif, renders, uploads both.

    Returns:
        The WGS84 bounds dict, or None if twi.tif is not available.
    """
    from app.services.design_generator import download_raster

    s3 = _s3_client()
    bucket = get_settings().minio_bucket

    cached = _load_cached_bounds(s3, bucket, parcel_id, tenant_id)
    if cached is not None:
        return cached

    tif = download_raster(parcel_id, tenant_id, "twi.tif")
    if not tif:
        logger.info("No twi.tif for parcel %s (tenant %s)", parcel_id, tenant_id)
        return None

    png, bounds = render_twi_overlay(tif)

    s3.put_object(
        Bucket=bucket,
        Key=overlay_png_key(parcel_id, tenant_id),
        Body=png,
        ContentType="image/png",
    )
    s3.put_object(
        Bucket=bucket,
        Key=overlay_bounds_key(parcel_id, tenant_id),
        Body=json.dumps(bounds).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info("Rendered TWI overlay for parcel %s (%d bytes)", parcel_id, len(png))
    return bounds
