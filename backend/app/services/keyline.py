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
# No line may hold an interior local high more than 5 cm above its
# neighbouring lows (prominence on the analysis DEM sampled every 0.1 m):
# water would stop in the dip before it. The trace never rises more than
# COUNTER_SLOPE_TOL_M above the lowest point it has reached, checked every
# NO_CLIMB_SAMPLE_M along each step, and placed lines are split where they
# still do (see `_falling_parts`). 3 cm keeps 2 cm below that limit; 2 m DEMs
# carry 1-3 cm of micro-relief per metre, so a tighter bound ends noticeably
# more lines early on hilly 2 m LiDAR test terrain.
COUNTER_SLOPE_TOL_M = 0.03
NO_CLIMB_SAMPLE_M = 0.1
# A keyline starts at its keypoint on the valley floor: its first steps cross
# the floor and climb the side slope (a few cm) before it falls away at
# grade, so the rule applies to its arms past this run (m). The trace leaves
# a rounded 2 m-cell floor within about 3 m; the keypoint stays the keyline's
# high point by design.
KEYLINE_START_FREE_M = 3.0
# Bisection steps for the smallest steer whose step does not climb (see
# `_walk`): 8 halvings of the steer range fix the heading to within about
# 0.2 degrees (4 mm sideways over a 1 m step).
NO_CLIMB_BISECTIONS = 8

# Every line is traced on the terrain at the design grade and emitted only
# where its real fall, measured on the analysis DEM as the elevation change
# over any GRADE_WINDOW_M run of the line, stays within MAX_LINE_GRADE, always
# away from drainage. Exact offsets of a keyline drift off grade and over
# humps on real terrain, so there are none.
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
# Seeds that give no usable line (flats, ridges, gaps between lines) are not
# retried. After this many such seeds the layout stops, which bounds the run
# time (each costs a trace, a few ms).
MAX_FAILED_SEEDS = 3000
# Wall-clock budget (s) of the layout's seed loop. The layout runs inside the
# request and the API gateway gives up on a proxied request after 30 s; the
# DEM download, analysis grid, keypoints and response building need a few
# seconds more. Past the budget the layout stops with what it has placed and
# reports `coverage_truncated` (large parcels on rough ground hit it).
LAYOUT_TIME_BUDGET_S = 20.0
# Default shortest line kept (m): shorter runs are not worth a ripping pass
# with a tractor. The user can change it (request field `min_line_m`).
DEFAULT_MIN_LINE_M = 100.0
# A new line is seeded one spacing across the slope from an existing line,
# every spacing along it. Its trace stops where it comes within this fraction
# of the spacing of another line, and what still comes closer is cut, so
# neighbouring lines never bunch below half the spacing.
CLEARANCE_FRACTION = 0.5
# A seed closer than this fraction of the spacing to an existing line is
# skipped: the ground there is already served by that line.
SEED_CLEARANCE_FRACTION = 0.75
# Drainage lines for the fall direction of lines: cells draining at least
# this area (m2). A keyline pattern moves water from the drainage lines towards
# the ridges, so every line starts (high end) next to drainage and falls away
# from it; 0.2 ha keeps the hollows that gather a field's runoff and leaves
# out the one-cell rills of a hillside.
DRAINAGE_MIN_AREA_M2 = 2000.0
# An arm ends where it has come back towards a drainage line by more than
# this (m) from the farthest it has been: past a ridge it would fall towards
# the next drainage line. Smaller than a rip-line spacing, so the cut only
# ignores wobble below the scale of the pattern (one cell, 2 m, cut lines on
# hilly 2 m LiDAR test terrain into many more short pieces).
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


def _walk(dem, transform, mask, x0, y0, grade, side, step, away=None, flat=None, free_m=0.0):
    """Points from (x0, y0) following the contour with the design grade.

    `away` = (distance grid, metres): the walk also ends once the grid value
    under it drops that much below the largest it has seen (the layout passes
    the distance to drainage, so a line stops closing in on a drainage line).
    `flat` is `dem.ravel().tolist()` when the caller walks the same DEM many
    times (Python list indexing is several times faster than numpy's).
    The elevation never rises more than `COUNTER_SLOPE_TOL_M` above the
    lowest it has reached, except over the first `free_m` metres (a keyline
    starts on the valley floor, where its first step climbs the side slope).
    """
    inv = ~transform
    ny, nx = mask.shape
    # Inline the inverse affine and the bilinear surface (same arithmetic as
    # `_z_many`): the walk is the hot loop of the layout.
    ia, ib, ic, id_, ie, if_ = inv.a, inv.b, inv.c, inv.d, inv.e, inv.f
    z = flat if flat is not None else np.asarray(dem, dtype=float).ravel().tolist()

    rmax, cmax, rk, ck = ny - 1.0, nx - 1.0, ny - 2, nx - 2

    def zf(px, py):
        c = ia * px + ib * py + ic - 0.5
        r = id_ * px + ie * py + if_ - 0.5
        r = 0.0 if r < 0.0 else (rmax if r > rmax else r)
        c = 0.0 if c < 0.0 else (cmax if c > cmax else c)
        r0 = int(r)
        c0 = int(c)
        r0 = rk if r0 > rk else r0
        c0 = ck if c0 > ck else c0
        fr, fc = r - r0, c - c0
        k = r0 * nx + c0
        top = z[k] * (1 - fc) + z[k + 1] * fc
        bot = z[k + nx] * (1 - fc) + z[k + nx + 1] * fc
        return top * (1 - fr) + bot * fr

    sub = max(1, int(math.ceil(step / NO_CLIMB_SAMPLE_M)))
    ts = [(k + 1) / sub for k in range(sub)]

    def step_low(px, py, lowest):
        """Lowest elevation reached by the end of the step from (x, y) to
        (px, py), from `lowest` before it, sampled `sub` times; None as soon
        as a sample is more than COUNTER_SLOPE_TOL_M above the lowest point
        before it. Same arithmetic as `zf`, inlined: this is the inner loop
        of the layout."""
        ca0 = ia * x + ib * y + ic - 0.5
        ra0 = id_ * x + ie * y + if_ - 0.5
        dcol = ia * (px - x) + ib * (py - y)
        drow = id_ * (px - x) + ie * (py - y)
        for t in ts:
            c = ca0 + t * dcol
            r = ra0 + t * drow
            r = 0.0 if r < 0.0 else (rmax if r > rmax else r)
            c = 0.0 if c < 0.0 else (cmax if c > cmax else c)
            r0 = int(r)
            c0 = int(c)
            r0 = rk if r0 > rk else r0
            c0 = ck if c0 > ck else c0
            fr, fc = r - r0, c - c0
            k = r0 * nx + c0
            v = ((z[k] * (1 - fc) + z[k + 1] * fc) * (1 - fr)
                 + (z[k + nx] * (1 - fc) + z[k + nx + 1] * fc) * fr)
            if not v <= lowest + COUNTER_SLOPE_TOL_M:     # climbs, or NaN
                return None
            if v < lowest:
                lowest = v
        return lowest

    pts = []
    x, y = x0, y0
    z0 = zf(x0, y0)
    zmin = z0
    travelled = 0.0
    headings = []
    window = max(1, int(round(TIGHT_TURN_RUN_M / step)))
    far = -math.inf
    h = step
    for _ in range(int(4 * (ny + nx) * abs(transform.a) / step) + 10):
        gx = (zf(x + h, y) - zf(x - h, y)) / (2 * h)
        gy = (zf(x, y + h) - zf(x, y - h)) / (2 * h)
        g = math.hypot(gx, gy)
        # Below the design grade the slope cannot carry the line: flat ground
        # or a ridge crest, so the line ends. No elevation (NaN) ends it too.
        if not math.isfinite(g) or g < grade:
            break
        z_here = zf(x, y)
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
        # Water runs along the line from its start: the line never climbs
        # more than COUNTER_SLOPE_TOL_M above the lowest point it has reached,
        # checked every NO_CLIMB_SAMPLE_M along the step (a step can bulge
        # over a bump between its ends on rough ground). Where the steer
        # above heads back up (below the target, after a dip) or the step
        # crosses a bump, it is turned downhill just enough (after a dip the
        # line so runs about level until its target, falling at the design
        # grade, comes down to it); where even the largest steer climbs
        # (across a valley axis), the line ends.
        if travelled < free_m:
            lowest = zf(nxp, nyp)
        else:
            lowest = step_low(nxp, nyp, zmin)
            if lowest is None:
                lo, hi = s, MAX_STEER
                ch = math.sqrt(1 - hi * hi)
                lowest = step_low(x + step * (ch * tx + hi * ux), y + step * (ch * ty + hi * uy), zmin)
                if lowest is None:
                    break
                for _ in range(NO_CLIMB_BISECTIONS):
                    mid = 0.5 * (lo + hi)
                    cm = math.sqrt(1 - mid * mid)
                    v = step_low(x + step * (cm * tx + mid * ux), y + step * (cm * ty + mid * uy), zmin)
                    if v is None:
                        lo = mid
                    else:
                        hi, lowest = mid, v
                s = hi
                ca = math.sqrt(1 - s * s)
                dx, dy = ca * tx + s * ux, ca * ty + s * uy
                nxp, nyp = x + step * dx, y + step * dy
        ri = int(math.floor(id_ * nxp + ie * nyp + if_))
        ci = int(math.floor(ia * nxp + ib * nyp + ic))
        if not (0 <= ri < ny and 0 <= ci < nx) or not mask[ri, ci]:
            break
        if away is not None:
            v = away[0][ri, ci]
            far = max(far, v)
            if v < far - away[1]:
                break
        # Over the free start the reference is where the line is; then the
        # lowest point it has reached.
        zmin = lowest if travelled < free_m else min(zmin, lowest)
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


def _arm(dem, transform, mask, x0, y0, grade, side, step, drainage=None, flat=None, free_m=0.0):
    """Points of one arm traced from (x0, y0) (start included) at `grade`,
    and how much farther from drainage its end is than its start (inf
    without `drainage`).

    `drainage` = (per-cell distance grid, function of points -> distances to
    the drainage lines): the arm stops where it closes in on a drainage line
    by more than `DRAINAGE_APPROACH_M` from the farthest it has been, and
    ends at that farthest point (beyond it, it would fall towards another
    drainage line). `flat` and `free_m` are passed to `_walk`.
    """
    away = None if drainage is None else (drainage[0], DRAINAGE_APPROACH_M + 2 * abs(transform.a))
    pts = [(x0, y0)] + _walk(dem, transform, mask, x0, y0, grade, side, step,
                             away=away, flat=flat, free_m=free_m)
    if drainage is None:
        return pts, math.inf
    dist = drainage[1](pts)
    closing = np.flatnonzero(dist < np.maximum.accumulate(dist) - DRAINAGE_APPROACH_M)
    stop = int(closing[0]) if len(closing) else len(pts)
    far = int(np.argmax(dist[:stop]))
    return pts[:far + 1], float(dist[far] - dist[0])


def trace_keyline(dem, transform, keypoint: dict, grade: float, parcel_mask,
                  drainage=None, flat=None) -> LineString:
    """Keyline through `keypoint`, in the DEM CRS (the guide `keyline_layout`
    starts from).

    Goes both ways across the slope; elevation falls `grade` per metre of line
    away from the valley and never climbs back (past `KEYLINE_START_FREE_M`
    from the keypoint). Each arm stops at the mask edge, where the slope is
    flatter than `grade` or has no elevation, where it cannot go on without
    climbing, or where the contour turns back on itself within
    `TIGHT_TURN_RUN_M` (over a sharp crest or drainage line, around a knoll
    or hollow; it then ends where that turn began); with `drainage` (see
    `_arm`) also where it is farthest from drainage. The line is oriented so
    that its left side is the uphill side. Empty when no arm moves.
    """
    mask = np.asarray(parcel_mask, dtype=bool)
    step = abs(transform.a) / TRACE_STEPS_PER_CELL
    x0, y0 = keypoint["x"], keypoint["y"]
    plus, _ = _arm(dem, transform, mask, x0, y0, grade, +1, step, drainage, flat, KEYLINE_START_FREE_M)
    minus, _ = _arm(dem, transform, mask, x0, y0, grade, -1, step, drainage, flat, KEYLINE_START_FREE_M)
    # `_walk` keeps uphill on the left of travel for side=+1 and on the right
    # for side=-1, so the reversed minus arm followed by the plus arm has
    # uphill on its left everywhere (no gradient needed at the keypoint,
    # which may be undefined next to nodata).
    coords = minus[::-1] + plus[1:]
    return LineString(coords) if len(coords) >= 2 else LineString()


def _z_many(dem: np.ndarray, inv: Affine, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear elevations at world points (cell values at cell centres); NaN where a
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


def _monotone_ranges(z: np.ndarray, tol: float) -> list:
    """Index ranges (i, j, high_at_end) of profile `z` (i < j, inclusive)
    along which, walked from the high end, no point rises more than `tol`
    above the lowest point before it, so no interior local high has a
    prominence above `tol`.

    A range whose highest point is interior (more than `tol` above both
    ends) is split there; a range that falls from its high end, dips and
    climbs back more than `tol` is split at the bottom of that dip and the
    rest is examined again.
    """
    out, todo = [], [(0, len(z) - 1)]
    while todo:
        i, j = todo.pop()
        if j <= i:
            continue
        seg = z[i:j + 1]
        k = i + int(np.argmax(seg))
        if z[k] - z[i] <= tol:
            high_at_end = False
        elif z[k] - z[j] <= tol:
            high_at_end = True
        else:
            todo += [(i, k), (k, j)]
            continue
        walked = seg[::-1] if high_at_end else seg
        climbs = np.flatnonzero(walked - np.minimum.accumulate(walked) > tol)
        if not len(climbs):
            out.append((i, j, high_at_end))
            continue
        # The dip bottom is past the start: the start is within `tol` of
        # the highest point, so the climb cannot begin there.
        dip = int(np.argmin(walked[:climbs[0] + 1]))
        if high_at_end:
            out.append((j - dip, j, True))
            todo.append((i, j - dip))
        else:
            out.append((i, i + dip, False))
            todo.append((i + dip, j))
    return sorted(out)


def _falling_parts(line: LineString, dem, transform, drain_dist, min_len: float) -> list:
    """`line` split into parts that each fall from one end without a
    counter-slope (`_monotone_ranges` with `COUNTER_SLOPE_TOL_M`: at any hump
    and at the bottom of any dip it climbs back out of); only parts at least
    `min_len` long whose low end is farther from drainage than their high
    end are kept (`drain_dist(points)` -> distances, or None when there is no
    drainage: then only the splits apply). So no emitted line has a
    counter-slope or sends water towards a drainage line. A line that needs
    no split is returned as it is.
    """
    from shapely.ops import substring

    d, z = _profile(line, dem, ~transform, abs(transform.a) / GRADE_SAMPLES_PER_CELL)
    if not np.isfinite(z).all():
        return []
    parts = []
    for i, j, high_at_end in _monotone_ranges(z, COUNTER_SLOPE_TOL_M):
        whole = i == 0 and j == len(z) - 1
        parts.append((line if whole else substring(line, d[i], d[j]), high_at_end))
    kept = []
    for a, high_at_end in parts:
        if a.length < min_len:
            continue
        ends = [a.coords[-1], a.coords[0]] if high_at_end else [a.coords[0], a.coords[-1]]
        dist = drain_dist(ends)
        if dist is None or dist[1] > dist[0]:
            kept.append(a)
    return kept


def keyline_layout(
    dem: np.ndarray,
    transform: Affine,
    trace_mask: np.ndarray,
    parcel_utm,
    keypoints: list,
    spacing_m: float,
    grade: float = DEFAULT_GRADE,
    max_lines: Optional[int] = None,
    min_line_m: float = DEFAULT_MIN_LINE_M,
    flow_accum: Optional[np.ndarray] = None,
    time_budget_s: Optional[float] = None,
) -> dict:
    """Keylines and lines traced at the design grade across the parcel.

    Each keypoint's keyline is traced at `grade` (both arms falling away from
    the valley) and is the guide the layout starts from. Every other line is
    traced on the terrain at `grade` too, from a seed one spacing across the
    slope (along the local normal) from an already placed line, every spacing
    along it; seeds nearest drainage go first. Rules for each line:

    - real fall within `MAX_LINE_GRADE` over every `GRADE_WINDOW_M` run
      (steeper stretches are cut out);
    - fall away from drainage: drainage lines are the cells of `flow_accum`
      (analysis cells) draining at least `DRAINAGE_MIN_AREA_M2`; a line runs
      from its high end on the drainage side to where it is farthest from
      drainage (the ridge), it is split at any hump and only parts whose low
      end is farther from drainage than their high end are kept;
    - no counter-slope: the trace never climbs more than
      `COUNTER_SLOPE_TOL_M` above the lowest point it has reached, and what
      still does is split at the bottom of the dip;
    - never closer than `CLEARANCE_FRACTION` x spacing to another line;
    - contiguous pieces are joined; lines shorter than `min_line_m` are
      dropped (keylines are kept down to `MIN_SEGMENT_M`, as the guide);
    - clipped to the parcel minus unfilled nodata.

    When the seeds next to placed lines run out, open ground nearest drainage
    seeds a new start. With `max_lines` set, only that many rows of lines are
    seeded out from the keylines (no new starts). Without drainage cells (or
    `flow_accum`) no fall direction is preferred.

    Returns {"lines": [entries], "coverage_pct": parcel % within half a
    spacing of a line, "coverage_truncated": bool (the seed limit
    `MAX_FAILED_SEEDS` or the time budget (`time_budget_s`, default
    `LAYOUT_TIME_BUDGET_S`) stopped the
    layout with ground left), "stopped_by": None | "seed_limit" |
    "time_budget", "failed_seeds":
    int}; entries are {geometry, direction ("keyline"|"line"), grade,
    max_grade_20m, valley}.
    """
    import heapq
    import time

    started = time.monotonic()
    budget_s = LAYOUT_TIME_BUDGET_S if time_budget_s is None else time_budget_s
    from rasterio import features
    from shapely.ops import unary_union

    empty = {"lines": [], "coverage_pct": 0.0, "coverage_truncated": False, "stopped_by": None,
             "failed_seeds": 0}
    region = _usable_area(parcel_utm, dem, transform)
    if region.is_empty or parcel_utm.area <= 0:
        return empty
    shape_ = dem.shape
    inv = ~transform
    cell = abs(transform.a)
    step = cell / TRACE_STEPS_PER_CELL
    cap = MAX_LINE_GRADE - GRADE_MARGIN
    clear_m = CLEARANCE_FRACTION * spacing_m
    trace_mask = np.asarray(trace_mask, dtype=bool) & np.isfinite(dem)
    work = features.rasterize([(region, 1)], out_shape=shape_, transform=transform,
                              fill=0, dtype="uint8").astype(bool) & trace_mask
    flat = np.asarray(dem, dtype=float).ravel().tolist()
    blocked = np.zeros(shape_, bool)   # within the clearance of a line: no trace
    served = np.zeros(shape_, bool)    # within the seed clearance of a line: no seed
    dead = np.zeros(shape_, bool)      # around seeds that gave no line

    # Drainage cells, and the distance to them of every cell (seed order).
    drain_tree = None
    if flow_accum is not None:
        rc = np.argwhere(np.nan_to_num(flow_accum) * abs(transform.a * transform.e)
                         >= DRAINAGE_MIN_AREA_M2)
        if len(rc):
            dx, dy = transform @ (rc[:, 1] + 0.5, rc[:, 0] + 0.5)
            drain_tree = shapely.STRtree(shapely.points(dx, dy))

    def drain_dist(pts):
        if drain_tree is None:
            return None
        xy = np.asarray(pts, dtype=float).reshape(-1, 2)
        _, dist = drain_tree.query_nearest(shapely.points(xy[:, 0], xy[:, 1]),
                                           return_distance=True, all_matches=False)
        return dist

    cell_dist = np.zeros(shape_)
    if drain_tree is not None:
        rows, cols = np.nonzero(trace_mask)
        cx, cy = transform @ (cols + 0.5, rows + 0.5)
        cell_dist[rows, cols] = drain_dist(np.column_stack([cx, cy]))

    def to_cell(x, y):
        c, r = inv @ (x, y)
        ri, ci = int(math.floor(r)), int(math.floor(c))
        return (ri, ci) if 0 <= ri < shape_[0] and 0 <= ci < shape_[1] else None

    def paint(geom, radii_targets):
        """Mark the cells whose centre lies within each radius of `geom`."""
        reach = max(r for r, _ in radii_targets)
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

    drainage = None if drain_tree is None else (cell_dist, drain_dist)

    def arm(x0, y0, side, mask):
        return _arm(dem, transform, mask, x0, y0, grade, side, step, drainage, flat)

    def oriented(pts, side):
        # `_walk` keeps uphill on the left of travel for side=+1 and on the
        # right for side=-1: flip the latter so uphill is always on the left.
        return pts if side > 0 else pts[::-1]

    def falls_away(line):
        return _falling_parts(line, dem, transform, drain_dist, MIN_SEGMENT_M)

    def valid(piece) -> list:
        """(piece, mean, worst) for the parts of `piece` within the cap and
        (for lines) falling away from drainage, at least MIN_SEGMENT_M."""
        out_ = []
        for part, _, _ in _grade_split(piece, dem, transform, cap, MIN_SEGMENT_M)[0]:
            for a in falls_away(part):
                for f in _grade_split(a, dem, transform, cap, MIN_SEGMENT_M)[0]:
                    if falls_away(f[0]) == [f[0]]:
                        out_.append(f)
        return out_

    out = []
    boxes = np.empty((0, 4))

    def place(line, valley) -> list:
        """Clip, check and emit `line`; returns the emitted geometries."""
        nonlocal boxes
        is_keyline = valley is not None
        pieces = []
        for piece in _clip(line, region):
            if piece.length < MIN_SEGMENT_M:
                continue
            px0, py0, px1, py1 = piece.bounds
            for i in np.flatnonzero((boxes[:, 0] <= px1 + clear_m) & (boxes[:, 2] >= px0 - clear_m)
                                    & (boxes[:, 1] <= py1 + clear_m) & (boxes[:, 3] >= py0 - clear_m)):
                if out[i]["geometry"].dwithin(piece, clear_m):
                    piece = piece.difference(out[i]["geometry"].buffer(clear_m))
                    if piece.is_empty:
                        break
            merged = shapely.line_merge(piece) if piece.geom_type == "MultiLineString" else piece
            for sub in shapely.get_parts(merged):
                if sub.geom_type != "LineString" or sub.length < MIN_SEGMENT_M:
                    continue
                if is_keyline:
                    pieces.extend(_grade_split(sub, dem, transform, cap, MIN_SEGMENT_M)[0])
                else:
                    pieces.extend(valid(sub))
        # Join pieces that meet end to end when the joined line still passes.
        if len(pieces) > 1 and not is_keyline:
            joined = shapely.line_merge(shapely.MultiLineString([p[0] for p in pieces]))
            parts = list(shapely.get_parts(joined))
            if len(parts) < len(pieces):
                rejoined = []
                for g in parts:
                    v = valid(g)
                    if len(v) == 1 and abs(v[0][0].length - g.length) < 1e-6:
                        rejoined.append(v[0])
                    else:
                        rejoined.extend(p for p in pieces if g.covers(p[0]))
                pieces = rejoined
        shortest = MIN_SEGMENT_M if is_keyline else min_line_m
        placed = []
        for geom, mean, worst in pieces:
            if geom.length < shortest:
                continue
            out.append({"geometry": geom, "direction": "keyline" if is_keyline else "line",
                        "grade": mean, "max_grade_20m": worst, "valley": valley})
            boxes = np.vstack([boxes, geom.bounds])
            paint(geom, [(SEED_CLEARANCE_FRACTION * spacing_m, served), (clear_m, blocked)])
            placed.append(geom)
        return placed

    heap, counter = [], 0

    def add_seeds(geom, gen):
        """Seeds one spacing across the slope from `geom`, every spacing."""
        nonlocal counter
        if max_lines is not None and gen > max_lines:
            return
        for s_ in np.arange(spacing_m / 2.0, geom.length, spacing_m):
            a = geom.interpolate(max(0.0, s_ - 1.0))
            b = geom.interpolate(min(geom.length, s_ + 1.0))
            tx, ty = b.x - a.x, b.y - a.y
            n = math.hypot(tx, ty)
            if n == 0:
                continue
            p = geom.interpolate(s_)
            for sign in (1, -1):
                x, y = p.x - sign * ty / n * spacing_m, p.y + sign * tx / n * spacing_m
                rc_ = to_cell(x, y)
                if rc_ is None or not work[rc_] or served[rc_]:
                    continue
                counter += 1
                heapq.heappush(heap, (float(cell_dist[rc_]), counter, x, y, gen))

    for v, kp in enumerate(keypoints):
        kl = trace_keyline(dem, transform, kp, grade, trace_mask, drainage, flat)
        if not kl.is_empty:
            for g in place(kl, v):
                add_seeds(g, 1)

    rows, cols = np.nonzero(work)
    order = np.argsort(cell_dist[rows, cols], kind="stable")
    order_rc = list(zip(rows[order].tolist(), cols[order].tolist()))
    start_at = 0
    failures, stopped_by = 0, None
    while True:
        seed = None
        while heap and seed is None:
            _, _, x, y, gen = heapq.heappop(heap)
            rc_ = to_cell(x, y)
            if rc_ is not None and work[rc_] and not served[rc_] and not dead[rc_]:
                seed = (x, y, gen)
        if seed is None and max_lines is None:
            # open ground, nearest drainage first
            while start_at < len(order):
                ri, ci = order_rc[start_at]
                start_at += 1
                if not served[ri, ci] and not dead[ri, ci]:
                    x, y = transform @ (ci + 0.5, ri + 0.5)
                    seed = (x, y, 1)
                    break
        if seed is None:
            break
        if failures >= MAX_FAILED_SEEDS:
            stopped_by = "seed_limit"
            break
        if time.monotonic() - started > budget_s:
            stopped_by = "time_budget"
            break
        x, y, gen = seed
        made, traced = [], []
        for side in (1, -1):
            pts, gain = arm(x, y, side, work & ~blocked)
            if len(pts) >= 2 and gain > 0:
                traced.append(LineString(oriented(pts, side)))
                if traced[-1].length >= min_line_m:      # else nothing could be kept
                    made.extend(place(traced[-1], None))
        for g in made:
            add_seeds(g, gen + 1)
        if not made:
            # Seeds on this contour would trace the same refused line: do not
            # seed along it again.
            paint(shapely.Point(x, y), [(clear_m, dead)])
            for t in traced:
                paint(t, [(cell, dead)])
            failures += 1

    covered = unary_union([o["geometry"].buffer(spacing_m / 2.0) for o in out]) if out else None
    coverage = 100.0 * covered.intersection(parcel_utm).area / parcel_utm.area if out else 0.0
    return {"lines": out, "coverage_pct": coverage, "coverage_truncated": stopped_by is not None,
            "stopped_by": stopped_by, "failed_seeds": failures}
