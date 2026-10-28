"""
Keyline detection: valley keypoint → guide line at target grade.
Pure Python, no geolibre dependency.
"""

import math
import numpy as np
from rasterio.transform import Affine
from typing import Optional


# A valley is a connected set of in-parcel cells whose flow accumulation is at
# least this fraction of the largest in-parcel accumulation (and the cell floor
# below), so a bigger neighbouring catchment outside the parcel never hides it.
VALLEY_ACCUM_FRACTION = 0.1
VALLEY_MIN_ACCUM_CELLS = 5
# Valleys whose floor drops less than this (m) between their upstream end and
# outlet inside the parcel are flats or noise, not a drainage line to key on.
MIN_VALLEY_RELIEF_M = 1.0
# Minimum grade difference (upstream steeper than downstream) for a floor slope
# break to count as a keypoint (convex -> concave transition).
MIN_SLOPE_BREAK = 0.01

_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _d8_target(dem: np.ndarray, r: int, c: int) -> Optional[tuple]:
    """Steepest-descent neighbour of (r, c), or None (pit, flat or edge)."""
    ny, nx = dem.shape
    best, best_slope = None, 0.0
    for dr, dc in _NEIGHBOURS:
        rr, cc = r + dr, c + dc
        if not (0 <= rr < ny and 0 <= cc < nx):
            continue
        slope = (dem[r, c] - dem[rr, cc]) / math.hypot(dr, dc)
        if slope > best_slope:
            best, best_slope = (rr, cc), slope
    return best


def _valley_floor_path(dem, flow_accum, mask, start):
    """Walk the D8 flow path upstream from `start`, following the largest
    accumulation among in-parcel cells that drain into the current cell."""
    ny, nx = dem.shape
    path = [start]
    seen = {start}
    r, c = start
    while True:
        best, best_acc = None, -1.0
        for dr, dc in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ny and 0 <= cc < nx) or (rr, cc) in seen:
                continue
            if not mask[rr, cc] or _d8_target(dem, rr, cc) != (r, c):
                continue
            if flow_accum[rr, cc] > best_acc:
                best, best_acc = (rr, cc), float(flow_accum[rr, cc])
        if best is None:
            return path
        path.append(best)
        seen.add(best)
        r, c = best


def _slope_break_index(dem, path, cell_size) -> Optional[int]:
    """Index in `path` (outlet first) of the largest convex->concave break:
    grade upstream of it exceeds grade downstream of it."""
    n = len(path)
    w = max(3, n // 5)
    if n < 2 * w + 1:
        return None
    z = np.array([dem[r, c] for r, c in path], dtype=float)
    steps = [math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
             for i in range(n - 1)]
    d = np.concatenate([[0.0], np.cumsum(steps)]) * cell_size
    best, best_delta = None, MIN_SLOPE_BREAK
    for k in range(w, n - w):
        up = (z[k + w] - z[k]) / (d[k + w] - d[k])
        down = (z[k] - z[k - w]) / (d[k] - d[k - w])
        if up - down > best_delta:
            best, best_delta = k, up - down
    return best


def _components(binary: np.ndarray) -> list:
    """8-connected components of a boolean array, each an (n, 2) row/col array."""
    ny, nx = binary.shape
    seen = np.zeros_like(binary, dtype=bool)
    out = []
    for r0, c0 in np.argwhere(binary):
        if seen[r0, c0]:
            continue
        stack, cells = [(int(r0), int(c0))], []
        seen[r0, c0] = True
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for dr, dc in _NEIGHBOURS:
                rr, cc = r + dr, c + dc
                if 0 <= rr < ny and 0 <= cc < nx and binary[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    stack.append((rr, cc))
        out.append(np.array(cells))
    return out


def detect_keypoints(
    dem: np.ndarray,
    transform: Affine,
    flow_accum: np.ndarray,
    parcel_mask: np.ndarray,
    max_valleys: int = 3,
) -> list:
    """Keypoints of the valleys inside the parcel, main valley first.

    Valleys come from `flow_accum` restricted to `parcel_mask`; each keypoint
    is the slope break on the valley floor profile, walked upstream along the
    D8 path from the valley's lowest in-parcel cell. Coordinates are in the
    DEM CRS (cell centres).
    """
    mask = np.asarray(parcel_mask, dtype=bool)
    if not mask.any():
        return []
    acc = np.where(mask, flow_accum, 0)
    threshold = max(VALLEY_MIN_ACCUM_CELLS, VALLEY_ACCUM_FRACTION * float(acc.max()))
    valley = acc >= threshold
    if not valley.any():
        return []
    components = _components(valley)
    cell_size = abs(transform.a)
    found = []
    for cells in components:
        zs = dem[cells[:, 0], cells[:, 1]]
        low = cells[int(np.argmin(zs))]
        path = _valley_floor_path(dem, flow_accum, mask, (int(low[0]), int(low[1])))
        floor = [dem[r, c] for r, c in path]
        if max(floor) - min(floor) < MIN_VALLEY_RELIEF_M:
            continue
        k = _slope_break_index(dem, path, cell_size)
        if k is None:
            continue
        row, col = path[k]
        x, y = transform @ (col + 0.5, row + 0.5)
        found.append({"row": row, "col": col, "x": float(x), "y": float(y),
                      "z": float(dem[row, col]), "valley_cells": int(len(cells))})
    found.sort(key=lambda k: k["valley_cells"], reverse=True)
    return found[:max_valleys]


def detect_keyline(
    dem: np.ndarray,
    transform: Affine,
    flow_accum: np.ndarray,
    target_grade: float = 0.005,
    min_height_m: float = 2.0,
) -> Optional[dict]:
    """Detect keypoint and generate keyline guide.

    Args:
        dem: 2D elevation array (meters)
        transform: Affine transform (CRS projected, e.g. EPSG:25830)
        flow_accum: D8 flow accumulation array (cells count)
        target_grade: Target grade for keyline (0.005 = 0.5%)
        min_height_m: Minimum valley depth to qualify

    Returns:
        GeoJSON-like dict with keypoint and keyline geometry, or None.
    """
    ny, nx = dem.shape

    # 1. Find valley bottom via max flow accumulation
    valley_row, valley_col = np.unravel_index(
        np.argmax(flow_accum), (ny, nx)
    )

    # 2. Extract valley profile (cross-section perpendicular to flow)
    half_width = min(20, nx // 4, ny // 4)
    row_start = max(0, valley_row - half_width)
    row_end = min(ny, valley_row + half_width + 1)

    profile = dem[row_start:row_end, valley_col]
    profile_idx = np.arange(len(profile))

    if len(profile) < 5:
        return None

    # 3. Compute 1D profile curvature (second derivative)
    curv = np.gradient(np.gradient(profile))

    # 4. Find concave→convex inflection (keypoint)
    # Concave = positive curvature, convex = negative
    # Keypoint is where curvature changes sign
    inflection = None
    for i in range(1, len(curv)):
        if curv[i - 1] > 0 and curv[i] <= 0:
            inflection = i
            break

    if inflection is None:
        return None

    keypoint_row = row_start + inflection
    keypoint_col = valley_col
    keypoint_x, keypoint_y = transform * (keypoint_col, keypoint_row)
    keypoint_z = float(dem[keypoint_row, keypoint_col])

    # 5. Generate keyline guide: from keypoint, follow contour at grade
    # Walk westward along hillside at target grade
    guide_points = [(keypoint_x, keypoint_y)]
    row, col = keypoint_row, keypoint_col
    target_drop = target_grade * abs(transform.a)  # vertical drop per cell east-west

    for step in range(min(100, nx // 2)):
        # Move west (col - 1), adjust north-south to maintain grade
        if col <= 0:
            break
        col -= 1
        current_z = dem[row, col]
        expected_z = keypoint_z - target_drop * (step + 1)

        # Find row that minimizes error with expected elevation
        best_row = row
        best_err = abs(dem[row, col] - expected_z)
        for dr in [-1, 0, 1]:
            r = row + dr
            if 0 <= r < ny:
                err = abs(dem[r, col] - expected_z)
                if err < best_err:
                    best_err = err
                    best_row = r
        row = best_row

        wx, wy = transform * (col, row)
        guide_points.append((wx, wy))

    return {
        "keypoint": {
            "type": "Point",
            "coordinates": [keypoint_x, keypoint_y, keypoint_z],
        },
        "keyline": {
            "type": "LineString",
            "coordinates": guide_points,
        },
        "properties": {
            "grade": target_grade,
            "length_m": sum(
            math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            for p1, p2 in zip(guide_points, guide_points[1:])
        ),
        },
    }
