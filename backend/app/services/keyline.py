"""
Keyline detection: valley keypoint → guide line at target grade.
Pure Python, no geolibre dependency.
"""

import math
import numpy as np
from rasterio.transform import Affine
from typing import Optional

import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon


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

# Pieces of a clipped keyline shorter than this (m) are not worth a ripping
# pass (a tractor cannot work them), so they are dropped.
MIN_SEGMENT_M = 15.0
# Default design grade of the keyline (fall per metre away from the valley).
DEFAULT_GRADE = 0.005

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


def _valley_floor_path(dem, flow_accum, valley, start):
    """Walk the D8 flow path upstream from `start`, following the largest
    accumulation among valley cells that drain into the current cell, so the
    profile never leaves the valley floor onto hillslope cells."""
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
            if not valley[rr, cc] or _d8_target(dem, rr, cc) != (r, c):
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
        path = _valley_floor_path(dem, flow_accum, valley, (int(low[0]), int(low[1])))
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


def _bilinear(dem: np.ndarray, r: float, c: float) -> float:
    ny, nx = dem.shape
    r = min(max(r, 0.0), ny - 1.0)
    c = min(max(c, 0.0), nx - 1.0)
    r0, c0 = min(int(r), ny - 2), min(int(c), nx - 2)
    fr, fc = r - r0, c - c0
    top = dem[r0, c0] * (1 - fc) + dem[r0, c0 + 1] * fc
    bot = dem[r0 + 1, c0] * (1 - fc) + dem[r0 + 1, c0 + 1] * fc
    return float(top * (1 - fr) + bot * fr)


def _z_at(dem, inv, x, y):
    c, r = inv @ (x, y)
    return _bilinear(dem, r - 0.5, c - 0.5)


def _gradient(dem, inv, a, e, x, y, h):
    """(dz/dx, dz/dy) in world units by central differences of the bilinear surface."""
    def z(px, py):
        c, r = inv @ (px, py)
        return _bilinear(dem, r - 0.5, c - 0.5)
    return ((z(x + h, y) - z(x - h, y)) / (2 * h), (z(x, y + h) - z(x, y - h)) / (2 * h))


def _walk(dem, transform, mask, x0, y0, grade, side, step):
    """Points from (x0, y0) following the contour with the design grade."""
    inv = ~transform
    ny, nx = mask.shape
    pts = []
    x, y = x0, y0
    prev = None
    z0 = _z_at(dem, inv, x0, y0)
    travelled = 0.0
    for _ in range(int(4 * (ny + nx) * abs(transform.a) / step) + 10):
        gx, gy = _gradient(dem, inv, transform.a, transform.e, x, y, step)
        g = math.hypot(gx, gy)
        # Below the design grade the slope cannot carry the line: flat ground
        # or a ridge crest, so the line ends.
        if g < grade:
            break
        ux, uy = -gx / g, -gy / g            # downhill unit vector
        tx, ty = -uy, ux                      # contour tangent
        if prev is None:
            tx, ty = side * tx, side * ty
        elif tx * prev[0] + ty * prev[1] < 0:
            tx, ty = -tx, -ty
        # Steer to the target elevation z0 - grade * length, not just to the
        # local slope, so that discretisation errors do not accumulate.
        need = (_z_at(dem, inv, x, y) - (z0 - grade * (travelled + step))) / (step * g)
        s = max(-1.0, min(1.0, need))         # dz/ds = -g * sin(alpha)
        ca = math.sqrt(1 - s * s)
        dx, dy = ca * tx + s * ux, ca * ty + s * uy
        nxp, nyp = x + step * dx, y + step * dy
        c, r = inv @ (nxp, nyp)
        ri, ci = int(math.floor(r)), int(math.floor(c))
        if not (0 <= ri < ny and 0 <= ci < nx) or not mask[ri, ci]:
            break
        pts.append((nxp, nyp))
        travelled += step
        prev = (dx, dy)
        x, y = nxp, nyp
    return pts


def trace_keyline(dem, transform, keypoint: dict, grade: float, parcel_mask) -> LineString:
    """Keyline through `keypoint`, in the DEM CRS.

    Goes both ways across the slope; elevation falls `grade` per metre of line
    away from the valley. Stops at the mask edge or where the slope is flatter
    than `grade` (ridge). The line is oriented so that its left side is the
    uphill side (`keyline_pattern` relies on this for "up"/"down").
    """
    mask = np.asarray(parcel_mask, dtype=bool)
    step = abs(transform.a)
    x0, y0 = keypoint["x"], keypoint["y"]
    first = _walk(dem, transform, mask, x0, y0, grade, +1, step)
    second = _walk(dem, transform, mask, x0, y0, grade, -1, step)
    coords = list(reversed(first)) + [(x0, y0)] + second
    if len(coords) < 2:
        return LineString()
    line = LineString(coords)
    # Orient: uphill must be on the left of travel.
    gx, gy = _gradient(dem, ~transform, transform.a, transform.e, x0, y0, step)
    (ax, ay), (bx, by) = coords[0], coords[-1]
    dx, dy = bx - ax, by - ay
    left_dot = (-dy) * gx + dx * gy        # left normal . uphill gradient
    if left_dot < 0:
        line = LineString(list(line.coords)[::-1])
    return line


def keyline_pattern(
    keylines: list,
    spacing_m: float,
    parcel_utm,
    max_lines: Optional[int] = None,
    min_segment_m: float = MIN_SEGMENT_M,
    grade: float = DEFAULT_GRADE,
) -> list:
    """Keylines plus true parallel offsets, clipped to the parcel.

    Offsets are made at multiples of `spacing_m` on both sides (positive =
    left = uphill = "up", per `trace_keyline`'s orientation) until they leave
    the parcel or `max_lines` per side. Pieces shorter than `min_segment_m`
    are dropped and the later of any two intersecting lines is removed
    (nearest offsets first, keylines in the order given). `grade` is the
    design grade reported on every line.
    """
    candidates = []  # (|k|, keyline index, signed k, line)
    for idx, kl in enumerate(keylines):
        if kl is None or kl.is_empty:
            continue
        reach = kl.hausdorff_distance(parcel_utm)
        kmax = int(reach // spacing_m) + 1
        if max_lines is not None:
            kmax = min(kmax, max_lines)
        candidates.append((0, idx, 0, kl))
        for k in range(1, kmax + 1):
            for sign in (1, -1):
                off = kl.offset_curve(sign * k * spacing_m)
                if off.is_empty:
                    continue
                candidates.append((k, idx, sign * k, off))
    candidates.sort(key=lambda t: (t[0], t[1], -t[2]))

    out = []
    for _, _, k, line in candidates:
        for piece in shapely.get_parts(line.intersection(parcel_utm)):
            if piece.geom_type != "LineString" or piece.length < min_segment_m:
                continue
            if any(piece.intersects(o["geometry"]) for o in out):
                continue
            out.append({"geometry": piece, "offset_m": float(k * spacing_m),
                        "direction": "keyline" if k == 0 else ("up" if k > 0 else "down"), "grade": grade})
    return out
