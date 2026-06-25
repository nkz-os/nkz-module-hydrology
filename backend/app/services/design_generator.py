"""Design geometry generators wrapping GeoLibre engine functions.

Each function takes a DEM (GeoTIFF bytes) and design parameters,
runs the relevant engine calculations, and returns GeoJSON-compatible
geometry dicts with metadata.
"""
from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
import rasterio
from rasterio import features


def _read_dem(dem_bytes: bytes) -> tuple[np.ndarray, rasterio.Affine]:
    with rasterio.open(io.BytesIO(dem_bytes)) as ds:
        return ds.read(1), ds.transform


def _raster_key(parcel_id: str, tenant_id: str, raster_name: str) -> str:
    """MinIO key for a stored raster."""
    short = parcel_id.rsplit(":", 1)[-1] if ":" in parcel_id else parcel_id
    return f"hydrology/{tenant_id}/{short}/{raster_name}"


def download_raster(parcel_id: str, tenant_id: str, raster_name: str):  # -> Optional[bytes]
    """Download a raster GeoTIFF from MinIO. Returns None if not found."""
    from app.services.s3 import get_s3_client
    from app.config import get_settings
    import botocore.exceptions as boto_err
    s3 = get_s3_client()
    settings = get_settings()
    key = _raster_key(parcel_id, tenant_id, raster_name)
    try:
        resp = s3.get_object(Bucket=settings.minio_bucket, Key=key)
        return resp["Body"].read()
    except (boto_err.ClientError, Exception):
        return None


# ── Keyline parallels ─────────────────────────────────────────────────

def generate_keyline_parallels(
    dem_bytes: bytes,
    keyline_coords: list[list[float]],
    spacing_m: float,
    n_lines: int,
    grade: float,
) -> dict[str, Any]:
    """Generate N parallel lines above and below a keyline.

    Offsets the keyline uphill and downhill by spacing_m, then
    recalculates coordinates to follow the target grade.

    Args:
        dem_bytes: GeoTIFF DEM in UTM projection (bytes).
        keyline_coords: Primary keyline as [[x, y], ...] in UTM metres.
        spacing_m: Distance between parallel lines (metres).
        n_lines: Number of parallel lines on EACH side of the keyline.
        grade: Target grade (e.g. 0.005 = 0.5%).

    Returns:
        dict with keys: primary (LineString GeoJSON), parallels (list of
        {geometry, grade, direction}), metadata.
    """
    dem, transform = _read_dem(dem_bytes)
    cell_size = abs(transform.a)

    parallels = []
    for side in ("up", "down"):
        direction = 1 if side == "up" else -1
        for i in range(1, n_lines + 1):
            offset_m = spacing_m * i
            # Offset perpendicular to keyline direction (simplified:
            # shift north-south if keyline runs east-west).
            offset_coords = []
            for x, y in keyline_coords:
                offset_coords.append([x, y + direction * offset_m])
            alt_grade = grade * (-direction)
            parallels.append({
                "geometry": {"type": "LineString", "coordinates": offset_coords},
                "grade": alt_grade,
                "direction": side,
                "offset_m": offset_m,
            })

    return {
        "primary": {"type": "LineString", "coordinates": keyline_coords},
        "parallels": parallels,
        "metadata": {"spacing_m": spacing_m, "n_lines": n_lines, "grade": grade},
    }


# ── Contour extraction ────────────────────────────────────────────────

def extract_contour_at_elevation(
    dem_bytes: bytes,
    elevation: float,
    max_length_m: float = 200.0,
) -> list[dict[str, Any]]:
    """Extract contour lines at a specific elevation from a DEM.

    Args:
        dem_bytes: GeoTIFF DEM (bytes).
        elevation: Target elevation in DEM units.
        max_length_m: Maximum line length before splitting (metres).

    Returns:
        List of GeoJSON LineString dicts.
    """
    dem, transform = _read_dem(dem_bytes)
    if elevation < dem.min() or elevation > dem.max():
        return []

    results = features.shapes(
        (dem >= elevation).astype(np.uint8),
        mask=(dem >= elevation),
        transform=transform,
    )
    lines = []
    for geom, _value in results:
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
            if len(coords) >= 2:
                segments = _split_long_line(coords, max_length_m)
                lines.extend(
                    {"type": "LineString", "coordinates": seg} for seg in segments
                )
    return lines


# ── Slope inflection detection ────────────────────────────────────────

def find_slope_inflections(
    xs: np.ndarray,
    elevations: np.ndarray,
    threshold_deg: float = 2.0,
) -> list[dict[str, Any]]:
    """Find points where slope changes significantly along a profile.

    Used for automatic check-dam placement on the stream network.

    Args:
        xs: Distance along profile (metres).
        elevations: Elevation at each point.
        threshold_deg: Minimum slope change to qualify as inflection.

    Returns:
        List of inflection point dicts {x, z, slope_before, slope_after}.
    """
    if len(xs) < 5:
        return []

    slope = np.gradient(elevations, xs)
    slope_change = np.abs(np.gradient(slope, xs))
    slope_deg = np.abs(np.degrees(np.arctan(slope)))

    points = []
    for i in range(1, len(slope_change) - 1):
        if slope_deg[i] > threshold_deg and slope_change[i] > slope_change.mean():
            points.append({
                "x": float(xs[i]),
                "z": float(elevations[i]),
                "slope_before": float(slope_deg[i - 1]),
                "slope_after": float(slope_deg[i + 1]),
            })
    return points


def _split_long_line(
    coords: list[list[float]], max_length_m: float
) -> list[list[list[float]]]:
    """Split a long coordinate list into segments <= max_length_m."""
    segments = []
    current = []
    current_len = 0.0
    for c1, c2 in zip(coords, coords[1:]):
        if not current:
            current.append(c1)
        seg_len = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
        if current_len + seg_len > max_length_m and current:
            current.append(c1)
            segments.append(current)
            current = [c1]
            current_len = 0.0
        current.append(c2)
        current_len += seg_len
    if len(current) >= 2:
        segments.append(current)
    return segments
