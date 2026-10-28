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

# Largest correction (sine of the angle off the contour) the trace applies per
# step to get back to its target elevation. Uncapped, one step that lands off
# target (a bump, a V-shaped valley axis) turns the line straight downhill and
# it runs down the valley instead of across the slope; 0.5 (30 degrees) still
# recovers 0.5 m of error per metre of slope gradient per step.
MAX_STEER = 0.5

# The parallels are offsets of the keyline continued straight beyond its
# ends; the heading of that continuation is measured over this length (m) of
# the line, so one noisy end step does not set it.
END_HEADING_M = 20.0

# The trace ends where it turns back (more than 90 degrees) within this run
# (m): a turning radius of about 13 m, tighter than a tractor with a ripper
# follows, which only happens where the contour circles a knoll or a hollow.
TIGHT_TURN_RUN_M = 20.0

# Cell size (m) of the grid the keyline analysis runs on. The keyline pattern
# is a field-scale design (rip lines ~10 m apart over slopes hundreds of metres
# long); on sub-metre LiDAR the drainage lines and the contour trace follow
# micro-relief (furrows, wheel ruts, field edges), so valleys break up and the
# trace stops or zigzags after a few tens of metres. Finer DEMs are averaged to
# this cell (integer block factor, so the grid stays aligned with the source);
# DEMs at or above it are used as they are. 2 m averages 16 cells of a 0.5 m
# LiDAR DEM and still puts several cells between two rip lines.
ANALYSIS_CELL_M = 2.0
# LiDAR leaves nodata where no ground return came back (trees, water, roofs).
# Gaps are interpolated from their edges up to this distance (m) on the
# analysis grid, which closes gaps up to about twice as wide; wider gaps stay
# nodata and are treated as outside the parcel.
NODATA_FILL_MAX_M = 20.0
# 3x3 smoothing passes over the interpolated cells (GDAL FillNodata), so the
# filled surface has no inverse-distance facets for the trace to follow.
NODATA_FILL_SMOOTHING = 2

_COS_45 = math.sqrt(0.5)
# Clearance (m) that keeps two lines of one pattern from touching.
_TOUCH_M = 0.01
_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _valley_floor_path(dem, flow_accum, valley, start):
    """Upstream walk along the valley floor from its outlet `start`.

    Each step goes to the valley neighbour with the largest accumulation
    strictly below the current cell's. Accumulation falls monotonically going
    upstream along a drainage line, so the walk follows the main stem across
    flats (where steepest descent recomputed on the DEM has no direction and
    the walk used to stop) and always ends.
    """
    ny, nx = valley.shape
    path = [start]
    r, c = start
    while True:
        here = float(flow_accum[r, c])
        best, best_acc = None, -math.inf
        for dr, dc in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ny and 0 <= cc < nx) or not valley[rr, cc]:
                continue
            a = float(flow_accum[rr, cc])
            if a < here and a > best_acc:
                best, best_acc = (rr, cc), a
        if best is None:
            return path
        path.append(best)
        r, c = best


def _block_reduce(arr: np.ndarray, fy: int, fx: int, how: str) -> np.ndarray:
    """Reduce `arr` over fy x fx blocks, ignoring NaN ("mean" or "max").

    Edge blocks are padded with NaN; an all-NaN block gives NaN."""
    ny, nx = arr.shape
    py, px = -ny % fy, -nx % fx
    a = np.pad(np.asarray(arr, dtype=float), ((0, py), (0, px)), constant_values=np.nan)
    a = a.reshape(a.shape[0] // fy, fy, a.shape[1] // fx, fx)
    valid = np.isfinite(a)
    n = valid.sum(axis=(1, 3))
    if how == "mean":
        out = np.where(valid, a, 0.0).sum(axis=(1, 3)) / np.maximum(n, 1)
    else:
        out = np.where(valid, a, -np.inf).max(axis=(1, 3))
    return np.where(n > 0, out, np.nan)


def analysis_grid(dem: np.ndarray, transform: Affine, flow_accum: np.ndarray) -> tuple:
    """DEM and accumulation on the keyline analysis grid.

    `dem` and `flow_accum` carry NaN for nodata. A DEM finer than
    `ANALYSIS_CELL_M` is block-averaged to it (valid cells only) and the
    accumulation takes the block maximum (a drainage line is one cell wide),
    rescaled to analysis cells. DEM gaps are then filled from their edges up
    to `NODATA_FILL_MAX_M`; wider gaps stay NaN. Unknown accumulation is 0.

    Returns (dem, flow_accum, transform) on the analysis grid.
    """
    from rasterio.fill import fillnodata

    fx = max(1, int(round(ANALYSIS_CELL_M / abs(transform.a))))
    fy = max(1, int(round(ANALYSIS_CELL_M / abs(transform.e))))
    dem = np.asarray(dem, dtype=float)
    acc = np.asarray(flow_accum, dtype=float)
    if fx > 1 or fy > 1:
        dem = _block_reduce(dem, fy, fx, "mean")
        acc = _block_reduce(acc, fy, fx, "max") / (fx * fy)
        transform = transform * Affine.scale(fx, fy)
    acc = np.nan_to_num(acc, nan=0.0, neginf=0.0, posinf=0.0)
    valid = np.isfinite(dem)
    if valid.any() and not valid.all():
        cell = max(abs(transform.a), abs(transform.e))
        dem = fillnodata(
            np.where(valid, dem, np.nan), mask=valid.astype("uint8"),
            max_search_distance=NODATA_FILL_MAX_M / cell,
            smoothing_iterations=NODATA_FILL_SMOOTHING,
        )
    return dem, acc, transform


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

    Valleys come from `flow_accum` restricted to `parcel_mask` (and to cells
    with elevation); each keypoint is the slope break on the valley floor
    profile, walked upstream from the valley's outlet (largest in-parcel
    accumulation) by decreasing accumulation. Coordinates are in the DEM CRS
    (cell centres).
    """
    # Cells without elevation (nodata) are outside the analysis.
    mask = np.asarray(parcel_mask, dtype=bool) & np.isfinite(dem)
    if not mask.any():
        return []
    acc = np.where(mask, np.nan_to_num(flow_accum, nan=0.0), 0)
    threshold = max(VALLEY_MIN_ACCUM_CELLS, VALLEY_ACCUM_FRACTION * float(acc.max()))
    valley = acc >= threshold
    if not valley.any():
        return []
    components = _components(valley)
    cell_size = abs(transform.a)
    found = []
    for cells in components:
        # The outlet is the cell with the largest accumulation.
        out = cells[int(np.argmax(acc[cells[:, 0], cells[:, 1]]))]
        path = _valley_floor_path(dem, acc, valley, (int(out[0]), int(out[1])))
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
    z0 = _z_at(dem, inv, x0, y0)
    travelled = 0.0
    headings = []
    window = max(1, int(round(TIGHT_TURN_RUN_M / step)))
    for _ in range(int(4 * (ny + nx) * abs(transform.a) / step) + 10):
        gx, gy = _gradient(dem, inv, transform.a, transform.e, x, y, step)
        g = math.hypot(gx, gy)
        # Below the design grade the slope cannot carry the line: flat ground
        # or a ridge crest, so the line ends. No elevation (NaN) ends it too.
        if not math.isfinite(g) or g < grade:
            break
        z_here = _z_at(dem, inv, x, y)
        if not math.isfinite(z_here):
            break
        ux, uy = -gx / g, -gy / g            # downhill unit vector
        # Contour tangent with uphill always on the same side of travel (left
        # for side=+1). Where the slope reverses under the line (a sharp crest
        # or drainage line) the tangent turns back; the turn check below ends
        # the line there.
        tx, ty = -side * uy, side * ux
        # Steer to the target elevation z0 - grade * length, not just to the
        # local slope, so that discretisation errors do not accumulate.
        need = (z_here - (z0 - grade * (travelled + step))) / (step * g)
        s = max(-MAX_STEER, min(MAX_STEER, need))   # dz/ds = -g * sin(alpha)
        ca = math.sqrt(1 - s * s)
        dx, dy = ca * tx + s * ux, ca * ty + s * uy
        nxp, nyp = x + step * dx, y + step * dy
        c, r = inv @ (nxp, nyp)
        ri, ci = int(math.floor(r)), int(math.floor(c))
        if not (0 <= ri < ny and 0 <= ci < nx) or not mask[ri, ci]:
            break
        pts.append((nxp, nyp))
        headings.append((dx, dy))
        travelled += step
        x, y = nxp, nyp
        # A contour that turns back within a short run circles a knoll or a
        # hollow, or folds over a sharp crest: no machine can follow it and
        # its offsets are loops. The line ends where that turn began (the
        # first step more than 45 degrees off the heading at the start of the
        # run). The first step (square across the valley axis, where the
        # contour has its apex) is not a heading the line keeps, so turns are
        # measured from the second step on, against the heading `window`
        # steps back (or the second heading, early in the line).
        back = max(1, len(headings) - 1 - window)
        if len(headings) > back + 1:
            hx, hy = headings[back]
            if dx * hx + dy * hy < 0:
                cut = next(k for k in range(back + 1, len(headings))
                           if headings[k][0] * hx + headings[k][1] * hy < _COS_45)
                del pts[cut:]
                break
    return pts


def trace_keyline(dem, transform, keypoint: dict, grade: float, parcel_mask) -> LineString:
    """Keyline through `keypoint`, in the DEM CRS.

    Goes both ways across the slope; elevation falls `grade` per metre of line
    away from the valley. Stops at the mask edge, where the slope is flatter
    than `grade` or has no elevation, or where the contour turns back on
    itself within `TIGHT_TURN_RUN_M` (over a sharp crest or drainage line,
    around a knoll or hollow); then it ends where that turn began. The line is
    oriented so that its left side is the uphill side (`keyline_pattern`
    relies on this for "up"/"down").
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


def _end_heading(line: LineString, at_start: bool) -> tuple:
    """Unit vector pointing out of `line` at one end, measured over the last
    `END_HEADING_M` of the line (or all of it when shorter)."""
    length = line.length
    span = min(END_HEADING_M, length)
    if at_start:
        a, b = line.interpolate(span), line.interpolate(0.0)
    else:
        a, b = line.interpolate(length - span), line.interpolate(length)
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 0 else (0.0, 0.0)


def _end_extensions(line: LineString, length: float) -> tuple:
    """Straight continuations of `line` beyond its start and its end, `length`
    long and running away from the line, as (before_start, after_end); either
    is None when its end has no heading. `before_start` ends at the line start,
    `after_end` begins at the line end."""
    coords = list(line.coords)
    out = []
    for at_start, (x, y) in ((True, coords[0]), (False, coords[-1])):
        ux, uy = _end_heading(line, at_start)
        if ux == 0.0 and uy == 0.0:
            out.append(None)
            continue
        far = (x + ux * length, y + uy * length)
        out.append(LineString([far, (x, y)] if at_start else [(x, y), far]))
    return tuple(out)


def _clip(line, parcel, cover) -> list:
    """LineString pieces of `line` inside `parcel`. A line that `cover` (the
    parcel grown by a hair) already covers is kept whole, with no splitting
    where a non-simple trace touches itself."""
    if line.is_empty:
        return []
    if cover.covers(line):
        return [line] if line.geom_type == "LineString" else list(shapely.get_parts(line))
    clipped = line.intersection(parcel)
    merged = shapely.line_merge(clipped) if clipped.geom_type == "MultiLineString" else clipped
    return [g for g in shapely.get_parts(merged) if g.geom_type == "LineString" and not g.is_empty]


def keyline_pattern(
    keylines: list,
    spacing_m: float,
    parcel_utm,
    max_lines: Optional[int] = None,
    min_segment_m: float = MIN_SEGMENT_M,
    grade: float = DEFAULT_GRADE,
) -> list:
    """Keylines plus true parallel offsets, clipped to the parcel.

    Each keyline is continued straight beyond both ends (along its heading
    over the last `END_HEADING_M`) far enough to leave the parcel; the
    parallels are offsets of that extended guide at multiples of `spacing_m`
    on both sides (positive = left = uphill = "up", per `trace_keyline`'s
    orientation) until they cover the parcel, or `max_lines` per side. Without
    the continuation the offsets would only span the keyline's own extent and
    wrap around its ends as arcs. The continuation itself is returned as
    direction "extension" (offset 0): it is the pattern line on the keyline's
    track where the terrain no longer defines the keyline.

    Lines are accepted nearest offset first (keylines in the order given, the
    main valley first). A later line is cut back where it comes within half a
    spacing of an accepted one, so patterns of neighbouring valleys meet at a
    seam instead of crossing; lines of one pattern are a full spacing apart
    and are not cut. Pieces shorter than `min_segment_m` are dropped. `grade`
    is the design grade reported on every line; every entry carries the index
    of its keyline as "keyline".
    """
    if parcel_utm.is_empty:
        return []
    minx, miny, maxx, maxy = parcel_utm.bounds
    # Long enough to leave the parcel from any point inside it.
    reach_len = math.hypot(maxx - minx, maxy - miny)
    rim = shapely.get_coordinates(shapely.segmentize(parcel_utm.boundary, max(spacing_m, 1.0)))
    rim_pts = shapely.points(rim)
    cover = parcel_utm.buffer(1e-6)

    candidates = []  # (|k|, kind, keyline index, -k, k, line, direction)
    for idx, kl in enumerate(keylines):
        if kl is None or kl.is_empty or kl.length == 0:
            continue
        before, after = _end_extensions(kl, reach_len)
        guide = LineString(([before.coords[0]] if before else []) + list(kl.coords)
                           + ([after.coords[-1]] if after else []))
        reach = float(shapely.distance(rim_pts, guide).max()) if len(rim_pts) else 0.0
        kmax = int(reach // spacing_m) + 1
        if max_lines is not None:
            kmax = min(kmax, max_lines)
        candidates.append((0, 0, idx, 0, 0, kl, "keyline"))
        for e in (before, after):
            if e is not None:
                candidates.append((0, 1, idx, 0, 0, e, "extension"))
        for k in range(1, kmax + 1):
            for sign in (1, -1):
                off = guide.offset_curve(sign * k * spacing_m)
                if off.is_empty:
                    continue
                candidates.append((k, 2, idx, -sign * k, sign * k, off,
                                   "up" if sign > 0 else "down"))
    candidates.sort(key=lambda t: t[:4])

    # Clearance from accepted lines: half a spacing from another valley's
    # pattern; within one pattern (an extension meets its keyline end to end,
    # offsets are a spacing apart) only enough to never touch.
    gap = spacing_m / 2.0
    out, zones = [], {}

    def zone(i, radius):
        if (i, radius) not in zones:
            zones[(i, radius)] = out[i]["geometry"].buffer(radius)
        return zones[(i, radius)]

    for _, _, idx, _, k, line, direction in candidates:
        for piece in _clip(line, parcel_utm, cover):
            if piece.length < min_segment_m:
                continue
            for i, o in enumerate(out):
                radius = gap if o["keyline"] != idx else _TOUCH_M
                if o["geometry"].dwithin(piece, radius):
                    piece = piece.difference(zone(i, radius))
                    if piece.is_empty:
                        break
            merged = shapely.line_merge(piece) if piece.geom_type == "MultiLineString" else piece
            for part in shapely.get_parts(merged):
                if part.geom_type != "LineString" or part.length < min_segment_m:
                    continue
                out.append({"geometry": part, "offset_m": float(k * spacing_m), "direction": direction,
                            "grade": grade, "keyline": idx})
    return out
