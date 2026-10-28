"""
Keyline detection: valley keypoint → guide line at target grade.
Pure Python, no geolibre dependency.
"""

import math
import numpy as np
from rasterio.transform import Affine
from typing import Optional

import shapely
from shapely.geometry import LineString


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

# Owner rule (spec, "Owner decision after real-terrain review"): a pattern
# line is emitted only where its real fall, measured on the analysis DEM as the
# elevation change over any GRADE_WINDOW_M run of the line, stays within
# MAX_LINE_GRADE. True parallels of a guide drift off grade as the terrain
# bends away from the guide; where they would exceed the cap a new guide is
# traced at the design grade and the pattern continues parallel to it.
MAX_LINE_GRADE = 0.015
GRADE_WINDOW_M = 20.0
# Lines are sampled for that measure every analysis cell / this factor. The
# fall over a window changes between samples; at one sample per cell the
# maximum on real terrain read up to 0.023 where 0.1 m sampling read more than
# the cap, at 1/8 of a cell (0.25 m) the gap to 0.05 m sampling is below 1e-3.
GRADE_SAMPLES_PER_CELL = 8
# Lines are kept only up to MAX_LINE_GRADE minus this margin, so the reported
# maximum stays within the cap however finely it is measured again (finer
# sampling read up to 3e-4 more on real terrain).
GRADE_MARGIN = 0.0005
# Seeds that give no usable guide (flats, slivers between patterns) are not
# retried. After this many such seeds the layout stops, which bounds the run
# time (each costs a trace, ~2 ms); a 38 ha hilly parcel settles by itself
# after ~1 500.
MAX_FAILED_SEEDS = 3000
# Drainage lines for the fall direction of guides: cells draining at least
# this area (m2). A keyline pattern moves water from the drainage lines towards
# the ridges, so every guide starts (high end) next to drainage and falls away
# from it; 0.2 ha keeps the hollows that gather a field's runoff and leaves
# out the one-cell rills of a hillside.
DRAINAGE_MIN_AREA_M2 = 2000.0
# An arm ends where it has come back towards a drainage line by more than
# this (m) from the farthest it has been: past a ridge it would fall towards
# the next drainage line. Smaller than a rip-line spacing, so the cut only
# ignores wobble below the scale of the pattern (one cell, 2 m, cut real-terrain
# guides into many more short pieces: coverage 72 % instead of 75 % on a hilly
# 38 ha parcel).
DRAINAGE_APPROACH_M = 10.0

# Trace steps per analysis cell. At one step per cell the line held the design
# grade only to about +-1 % per 20 m on a rounded valley (and lines are kept
# only within the 1.5 % cap); half-cell steps hold it to about +-0.5 %.
TRACE_STEPS_PER_CELL = 2

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
# A guide's highest point within this (m) of an end counts as its high end.
_HIGH_END_M = 1.0
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
    oriented so that its left side is the uphill side (`keyline_layout`
    relies on this for "up"/"down").
    """
    mask = np.asarray(parcel_mask, dtype=bool)
    step = abs(transform.a) / TRACE_STEPS_PER_CELL
    x0, y0 = keypoint["x"], keypoint["y"]
    first = _walk(dem, transform, mask, x0, y0, grade, +1, step)
    second = _walk(dem, transform, mask, x0, y0, grade, -1, step)
    coords = list(reversed(first)) + [(x0, y0)] + second
    if len(coords) < 2:
        return LineString()
    # Orient: uphill must be on the left of travel. `_walk` keeps uphill on
    # the left for side=+1 and on the right for side=-1, so `coords` (first
    # arm reversed, then the second) has uphill on its right everywhere:
    # reversing it is exact and needs no gradient at the keypoint (which may
    # be undefined next to nodata).
    return LineString(coords[::-1])


def _z_many(dem: np.ndarray, inv: Affine, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear elevations at world points (vectorised `_z_at`); NaN where a
    neighbouring cell has no elevation."""
    ny, nx = dem.shape
    c, r = inv @ (np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    r = np.clip(r - 0.5, 0.0, ny - 1.0)
    c = np.clip(c - 0.5, 0.0, nx - 1.0)
    r0 = np.minimum(r.astype(int), ny - 2)
    c0 = np.minimum(c.astype(int), nx - 2)
    fr, fc = r - r0, c - c0
    top = dem[r0, c0] * (1 - fc) + dem[r0, c0 + 1] * fc
    bot = dem[r0 + 1, c0] * (1 - fc) + dem[r0 + 1, c0 + 1] * fc
    return top * (1 - fr) + bot * fr


def _profile(line: LineString, dem, inv, step: float) -> tuple:
    """Distances along `line` (about `step` apart, ends included) and the
    elevations there."""
    xy = shapely.get_coordinates(line)
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(math.ceil(s[-1] / step)) + 1)
    d = np.linspace(0.0, s[-1], n)
    return d, _z_many(dem, inv, np.interp(d, s, xy[:, 0]), np.interp(d, s, xy[:, 1]))


def _window_falls(d: np.ndarray, z: np.ndarray, window_m: float) -> tuple:
    """Fall (|dz| / run) over every window of about `window_m` along a
    profile, and the sample count per window. A profile shorter than the
    window is one window."""
    step = d[1] - d[0] if len(d) > 1 else 0.0
    w = max(1, int(round(window_m / step))) if step > 0 else 1
    w = min(w, len(d) - 1)
    run = d[w:] - d[:-w]
    return np.abs(z[w:] - z[:-w]) / np.where(run > 0, run, np.inf), w


def line_grade(line: LineString, dem, transform, window_m: float = GRADE_WINDOW_M) -> tuple:
    """(mean fall, maximum fall) of `line` over `window_m` runs, on `dem`.
    NaN when the line touches a cell without elevation."""
    d, z = _profile(line, dem, ~transform, abs(transform.a) / GRADE_SAMPLES_PER_CELL)
    if not np.isfinite(z).all():
        return math.nan, math.nan
    falls, _ = _window_falls(d, z, window_m)
    return float(falls.mean()), float(falls.max())


def _grade_split(line: LineString, dem, transform, cap: float, min_len: float) -> tuple:
    """Pieces of `line` whose every `GRADE_WINDOW_M` run falls at most `cap`.

    A run steeper than the cap (or touching nodata) removes all its samples.
    Returns (pieces, rejected) where pieces are (LineString, mean, max) at
    least `min_len` long and rejected are the midpoints (x, y) of the removed
    stretches, where the terrain asks for a new guide.
    """
    from shapely.ops import substring

    d, z = _profile(line, dem, ~transform, abs(transform.a) / GRADE_SAMPLES_PER_CELL)
    n = len(d)
    bad = ~np.isfinite(z)
    falls, w = _window_falls(d, np.where(bad, 0.0, z), GRADE_WINDOW_M)
    steep = (falls > cap) | bad[w:] | bad[:-w]
    # every sample of a steep window is removed
    bad |= np.convolve(steep.astype(float), np.ones(w + 1))[:n] > 0
    pieces, rejected = [], []
    edges = np.flatnonzero(np.diff(bad.astype(np.int8))) + 1
    for k, j in zip(np.concatenate([[0], edges]), np.concatenate([edges, [n]]) - 1):
        if bad[k]:
            mid = line.interpolate((d[k] + d[j]) / 2.0)
            rejected.append((mid.x, mid.y))
        elif d[j] - d[k] >= min_len:
            part = substring(line, d[k], d[j])
            mean, worst = line_grade(part, dem, transform)
            if np.isfinite(worst) and worst <= cap:
                pieces.append((part, mean, worst))
            else:
                rejected.append((part.interpolate(0.5, normalized=True).x,
                                 part.interpolate(0.5, normalized=True).y))
    return pieces, rejected


def _dilate(m: np.ndarray) -> np.ndarray:
    """Cells of `m` and their 8 neighbours."""
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= out[:, :-1]
    out[:, :-1] |= out[:, 1:].copy()
    return out


def _clip(line, region) -> list:
    """LineString pieces of `line` inside `region`."""
    if line.is_empty:
        return []
    clipped = line.intersection(region)
    merged = shapely.line_merge(clipped) if clipped.geom_type == "MultiLineString" else clipped
    return [g for g in shapely.get_parts(merged) if g.geom_type == "LineString" and not g.is_empty]


def _usable_area(parcel_utm, dem, transform):
    """Parcel minus the cells without elevation, grown by one cell so that no
    sampled elevation on a kept line reads a nodata neighbour."""
    from rasterio import features
    from shapely.geometry import shape

    missing = ~np.isfinite(dem)
    if not missing.any():
        return parcel_utm
    holes = [shape(g) for g, v in features.shapes(missing.astype("uint8"), mask=missing,
                                                  transform=transform) if v == 1]
    cell = max(abs(transform.a), abs(transform.e))
    return parcel_utm.difference(shapely.union_all(holes).buffer(cell, join_style="mitre"))


def keyline_layout(
    dem: np.ndarray,
    transform: Affine,
    trace_mask: np.ndarray,
    parcel_utm,
    keypoints: list,
    spacing_m: float,
    grade: float = DEFAULT_GRADE,
    max_lines: Optional[int] = None,
    min_segment_m: float = MIN_SEGMENT_M,
    flow_accum: Optional[np.ndarray] = None,
) -> dict:
    """Keylines, their parallels and new guides covering the parcel.

    Each keypoint's keyline (traced at `grade`) is a guide. Parallels are
    true offsets of a guide at multiples of `spacing_m` on both sides
    (positive = left = uphill = "up", per `trace_keyline`'s orientation),
    kept only where their real fall stays within `MAX_LINE_GRADE` over every
    `GRADE_WINDOW_M` run (owner rule). A side stops at the first offset that
    keeps nothing. Where an offset was too steep, a new guide (direction
    "guide") is traced at `grade` from that spot, one spacing beyond the last
    kept line, with the keyline's tracing rules; uncovered ground next to the
    pattern seeds guides too, until the parcel is covered or no seed takes.
    With `max_lines` set, only the keylines and up to that many parallels per
    side are drawn (no new guides).

    Lines are clipped to the parcel minus unfilled nodata. Lines of a later
    guide are cut back where they come within half a spacing of an earlier
    guide's line (patterns meet at a seam, never cross). Every entry carries
    its measured `grade` (mean fall) and `max_grade_20m`; pieces shorter than
    `min_segment_m` are dropped. Guides are processed nearest offset first,
    keylines (main valley first) before seeded guides.

    Fall direction (spec: water moves from the valleys towards the ridges):
    drainage lines are the cells of `flow_accum` (analysis cells) draining at
    least `DRAINAGE_MIN_AREA_M2`. Each keyline arm, and the one arm a seeded
    guide keeps, starts at its high end and ends where it is farthest from
    drainage (the ridge between two drainage lines); a seeded guide keeps the
    arms that move away from drainage, each as its own guide starting at the
    seed; every emitted guide piece is split at its highest point and only
    the parts falling away from drainage are kept, so no guide falls towards a
    valley. Without drainage cells (or `flow_accum`) no direction is preferred.

    Returns {"lines": [entries], "coverage_truncated": bool (the seed limit
    `MAX_FAILED_SEEDS` stopped the layout), "failed_seeds": int}; entries are
    {geometry, direction ("keyline"|"guide"|"up"|"down"), offset_m (from its
    guide), grade, max_grade_20m, guide, valley}.
    """
    from rasterio import features

    region = _usable_area(parcel_utm, dem, transform)
    if region.is_empty:
        return {"lines": [], "coverage_truncated": False, "failed_seeds": 0}
    shape_ = dem.shape
    trace_mask = np.asarray(trace_mask, dtype=bool) & np.isfinite(dem)
    work = features.rasterize([(region, 1)], out_shape=shape_, transform=transform,
                              fill=0, dtype="uint8").astype(bool) & trace_mask
    covered = np.zeros(shape_, bool)   # within half a spacing of a kept line
    near = np.zeros(shape_, bool)      # within one spacing of a kept line
    dead = np.zeros(shape_, bool)      # around seeds whose guide kept nothing
    rim = shapely.points(shapely.get_coordinates(
        shapely.segmentize(parcel_utm.boundary, max(spacing_m, 1.0))))
    gap = spacing_m / 2.0
    cap = MAX_LINE_GRADE - GRADE_MARGIN
    inv = ~transform
    out, zones, seeds = [], {}, []

    def paint(geom, radii_targets):
        """Mark the cells whose centre lies within each radius of `geom` in
        its target array (radii in decreasing order)."""
        reach = radii_targets[0][0]
        minx, miny, maxx, maxy = geom.bounds
        ca, rb = inv @ (minx - reach, miny - reach)
        cb, ra = inv @ (maxx + reach, maxy + reach)
        r0, c0 = max(0, int(math.floor(min(ra, rb)))), max(0, int(math.floor(min(ca, cb))))
        r1 = min(shape_[0], int(math.ceil(max(ra, rb))) + 1)
        c1 = min(shape_[1], int(math.ceil(max(ca, cb))) + 1)
        if r1 <= r0 or c1 <= c0:
            return
        cc, rr = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
        xs, ys = transform @ (cc.ravel(), rr.ravel())
        dist = shapely.distance(shapely.points(xs, ys), geom).reshape(cc.shape)
        for radius, target in radii_targets:
            target[r0:r1, c0:c1] |= dist <= radius

    def zone(i, radius):
        if (i, radius) not in zones:
            zones[(i, radius)] = out[i]["geometry"].buffer(radius)
        return zones[(i, radius)]

    boxes = np.empty((0, 4))  # bounds of the kept lines, to skip far ones

    def accept(line, gid, valley, direction, offset) -> bool:
        nonlocal boxes
        kept = False
        for piece in _clip(line, region):
            if piece.length < min_segment_m:
                continue
            good, rejected = _grade_split(piece, dem, transform, cap, min_segment_m)
            seeds.extend(rejected)
            for part, _, _ in good:
                px0, py0, px1, py1 = part.bounds
                for i in np.flatnonzero((boxes[:, 0] <= px1 + gap) & (boxes[:, 2] >= px0 - gap)
                                        & (boxes[:, 1] <= py1 + gap) & (boxes[:, 3] >= py0 - gap)):
                    o = out[i]
                    radius = gap if o["guide"] != gid else _TOUCH_M
                    if o["geometry"].dwithin(part, radius):
                        part = part.difference(zone(i, radius))
                        if part.is_empty:
                            break
                merged = shapely.line_merge(part) if part.geom_type == "MultiLineString" else part
                for sub in shapely.get_parts(merged):
                    if sub.geom_type != "LineString" or sub.length < min_segment_m:
                        continue
                    # Measured again on what is emitted: never above the cap.
                    finals = _grade_split(sub, dem, transform, cap, min_segment_m)[0]
                    if direction == "guide":
                        # a guide starts high next to drainage and falls away
                        finals = [f for piece_ in finals for arm_ in falls_away(piece_[0])
                                  for f in _grade_split(arm_, dem, transform, cap, min_segment_m)[0]
                                  if falls_away(f[0]) == [f[0]]]
                    for final, mean, worst in finals:
                        boxes = np.vstack([boxes, final.bounds])
                        out.append({"geometry": final, "direction": direction,
                                    "offset_m": float(offset), "grade": mean,
                                    "max_grade_20m": worst, "guide": gid, "valley": valley})
                        paint(final, [(spacing_m, near), (gap, covered)])
                        kept = True
        return kept

    guides = []  # [line, gid, next k, open sides, kmax]

    def add_guide(line, valley, direction) -> bool:
        gid = len(guides)
        if line is None or line.is_empty or line.length == 0:
            return False
        if not accept(line, gid, valley, direction, 0.0):
            return False
        reach = float(shapely.distance(rim, line).max()) if len(rim) else 0.0
        kmax = int(reach // spacing_m) + 1
        if max_lines is not None:
            kmax = min(kmax, max_lines)
        guides.append([line, gid, 1, {1, -1} if kmax >= 1 else set(), kmax])
        return True

    # Drainage cells and the distance to them, for the fall direction.
    drain_tree = None
    if flow_accum is not None:
        cell_area = abs(transform.a * transform.e)
        rc = np.argwhere(np.nan_to_num(flow_accum) * cell_area >= DRAINAGE_MIN_AREA_M2)
        if len(rc):
            dx, dy = transform @ (rc[:, 1] + 0.5, rc[:, 0] + 0.5)
            drain_tree = shapely.STRtree(shapely.points(dx, dy))
    step = abs(transform.a) / TRACE_STEPS_PER_CELL

    def drain_dist(pts):
        if drain_tree is None:
            return None
        xy = np.asarray(pts, dtype=float)
        _, dist = drain_tree.query_nearest(shapely.points(xy[:, 0], xy[:, 1]), return_distance=True,
                                           all_matches=False)
        return dist

    def arm(x0, y0, side, mask):
        """Points of one arm from (x0, y0), cut where it is farthest from
        drainage (beyond that it would fall towards another drainage line),
        and how much farther from drainage its end is than its start."""
        pts = [(x0, y0)] + _walk(dem, transform, mask, x0, y0, grade, side, step)
        dist = drain_dist(pts)
        if dist is None:
            return pts, math.inf
        # Stop where the arm closes in on a drainage line (by more than
        # DRAINAGE_APPROACH_M from the farthest it has been), then end there.
        closing = np.flatnonzero(dist < np.maximum.accumulate(dist) - DRAINAGE_APPROACH_M)
        stop = int(closing[0]) if len(closing) else len(pts)
        far = int(np.argmax(dist[:stop]))
        return pts[:far + 1], float(dist[far] - dist[0])

    def falls_away(line):
        """`line` split at its highest point into arms that each start high;
        only arms whose low end is farther from drainage than their high end
        are kept, so a guide never sends water towards a drainage line."""
        from shapely.ops import substring

        d, z = _profile(line, dem, inv, abs(transform.a) / GRADE_SAMPLES_PER_CELL)
        if not np.isfinite(z).any():
            return []
        k = int(np.nanargmax(z))
        if d[k] <= _HIGH_END_M:                                    # already starts high
            arms = [(line, False)]
        elif line.length - d[k] <= _HIGH_END_M:                    # ends high
            arms = [(line, True)]
        else:
            arms = [(substring(line, 0.0, d[k]), True), (substring(line, d[k], line.length), False)]
        kept = []
        for a, high_at_end in arms:
            if a.length < min_segment_m:
                continue
            ends = [a.coords[-1], a.coords[0]] if high_at_end else [a.coords[0], a.coords[-1]]
            dist = drain_dist(ends)
            if dist is None or dist[1] > dist[0]:
                kept.append(a)
        return kept

    def oriented(pts, side):
        # `_walk` keeps uphill on the left of travel for side=+1 and on the
        # right for side=-1: flip the latter so uphill is always on the left.
        return pts if side > 0 else pts[::-1]

    def keyline_from(kp):
        plus, _ = arm(kp["x"], kp["y"], +1, trace_mask)
        minus, _ = arm(kp["x"], kp["y"], -1, trace_mask)
        coords = oriented(minus, -1)[:-1] + oriented(plus, +1)
        return LineString(coords) if len(coords) >= 2 else None

    def guides_from(x0, y0, mask):
        """The arms from a seed that move away from drainage, each a guide
        whose high end is the seed."""
        out_arms = []
        for side in (1, -1):
            pts, gain = arm(x0, y0, side, mask)
            if len(pts) >= 2 and gain > 0:
                out_arms.append(LineString(oriented(pts, side)))
        return out_arms

    for v, kp in enumerate(keypoints):
        add_guide(keyline_from(kp), v, "keyline")

    failures = 0
    truncated = False
    while True:
        open_guides = [g for g in guides if g[3]]
        if open_guides:
            g = min(open_guides, key=lambda t: (t[2], t[1]))
            line, gid, k, sides, kmax = g
            for side in sorted(sides, reverse=True):
                off = line.offset_curve(side * k * spacing_m)
                kept = (not off.is_empty) and accept(off, gid, None, "up" if side > 0 else "down",
                                                     side * k * spacing_m)
                if not kept or k >= kmax:
                    sides.discard(side)
            g[2] = k + 1
            continue
        if max_lines is not None:
            break
        seed = None
        while seeds and seed is None:
            x, y = seeds.pop()
            c, r = inv @ (x, y)
            ri, ci = int(math.floor(r)), int(math.floor(c))
            if 0 <= ri < shape_[0] and 0 <= ci < shape_[1] and work[ri, ci] \
                    and not covered[ri, ci] and not dead[ri, ci]:
                seed = (ri, ci)
        if seed is None:
            # One spacing beyond the kept lines first (the next line of the
            # pattern), then open ground away from any line, then what is left
            # between half a spacing and a spacing from lines.
            free = work & ~covered & ~dead
            far = free & ~near
            ring = far & _dilate(near)
            pick = next((m for m in (ring, far, free) if m.any()), None)
            if pick is None:
                break
            ri, ci = (int(v) for v in np.argwhere(pick)[0])
            seed = (ri, ci)
        if failures >= MAX_FAILED_SEEDS:
            # Ground is left that might still take a guide.
            truncated = True
            break
        ri, ci = seed
        x, y = transform @ (ci + 0.5, ri + 0.5)
        kp = {"row": ri, "col": ci, "x": float(x), "y": float(y), "z": float(dem[ri, ci])}
        # A new guide runs over ground the pattern does not cover yet: where it
        # reaches another line's half spacing it would be cut there anyway.
        made = [add_guide(g, None, "guide") for g in guides_from(kp["x"], kp["y"], trace_mask & ~covered)]
        if not any(made):
            # Nothing usable from here (flat, nodata edge, squeezed between
            # patterns): do not seed this spot again.
            paint(shapely.Point(x, y), [(gap, dead)])
            failures += 1
    return {"lines": out, "coverage_truncated": truncated, "failed_seeds": failures}
