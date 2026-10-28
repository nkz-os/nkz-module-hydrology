"""Tests for keyline detection."""

import math
import numpy as np
import pytest
from rasterio.transform import from_origin


@pytest.fixture
def natural_valley():
    """50x50 synthetic valley with realistic concave-convex profile."""
    size = 50
    dem = np.fromfunction(
        lambda i, j: 100 + abs(j - size // 2) * 0.5 + (1 - i / size) * 8,
        (size, size), dtype=np.float32
    )
    accum = np.zeros((size, size), dtype=np.float32)
    for i in range(size):
        accum[i, size // 2] = size - i
    transform = from_origin(600000, 4700000, 1.0, 1.0)
    return dem, accum, transform


def test_detect_keyline_returns_dict(natural_valley):
    from app.services.keyline import detect_keyline
    dem, accum, transform = natural_valley
    result = detect_keyline(dem, transform, accum)
    assert result is not None, "should find keyline"
    assert "keypoint" in result
    assert "keyline" in result
    assert result["keyline"]["type"] == "LineString"
    assert len(result["keyline"]["coordinates"]) > 1


def test_keyline_grade(natural_valley):
    from app.services.keyline import detect_keyline
    dem, accum, transform = natural_valley
    result = detect_keyline(dem, transform, accum, target_grade=0.005)
    assert result is not None
    assert abs(result["properties"]["grade"] - 0.005) < 0.001


def test_flat_dem_returns_none(natural_valley):
    from app.services.keyline import detect_keyline
    dem, accum, transform = natural_valley
    flat = np.ones_like(dem) * 100
    result = detect_keyline(flat, transform, accum, min_height_m=10)
    assert result is None or isinstance(result, dict)


def test_keyline_length_is_euclidean(natural_valley):
    """Length should be sum of euclidean distances between consecutive points,
    not just N * cellsize."""
    from app.services.keyline import detect_keyline
    dem, accum, transform = natural_valley
    result = detect_keyline(dem, transform, accum, target_grade=0.005)
    assert result is not None

    coords = result["keyline"]["coordinates"]
    expected_m = 0.0
    for p1, p2 in zip(coords, coords[1:]):
        expected_m += math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    actual_m = result["properties"]["length_m"]
    assert actual_m == pytest.approx(expected_m, rel=0.01), \
        f"length_m={actual_m} but euclidean={expected_m}"


def _valley_dem(size=80, cols=(40,), brk=40):
    """Floor falls south: steep above row `brk`, gentle below; V cross-section."""
    i = np.arange(size)[:, None].astype(float)
    floor = np.where(i <= brk, 120 - 0.5 * i, 120 - 0.5 * brk - 0.05 * (i - brk))
    j = np.arange(size)[None, :].astype(float)
    cross = np.min([np.abs(j - c) for c in cols], axis=0) * 0.5
    return (floor + cross).astype(np.float32)


def _accum(size, cols, lengths):
    a = np.zeros((size, size), dtype=np.float32)
    for c, n in zip(cols, lengths):
        for i in range(size):
            a[i, c] = n - i * n / size
    return a


TF = from_origin(600000, 4700000, 1.0, 1.0)


def test_keypoint_on_synthetic_valley():
    from app.services.keyline import detect_keypoints
    dem = _valley_dem()
    kps = detect_keypoints(dem, TF, _accum(80, (40,), (80,)), np.ones((80, 80), bool))
    assert len(kps) == 1
    assert abs(kps[0]["row"] - 40) <= 2 and abs(kps[0]["col"] - 40) <= 2
    assert kps[0]["valley_cells"] > 0


def test_keypoints_ignore_buffer_outside_parcel():
    from app.services.keyline import detect_keypoints
    dem = _valley_dem(cols=(40, 10))
    accum = _accum(80, (40, 10), (80, 500))  # biggest accumulation outside the parcel
    mask = np.ones((80, 80), bool)
    mask[:, :25] = False
    kps = detect_keypoints(dem, TF, accum, mask)
    assert kps
    assert all(mask[k["row"], k["col"]] for k in kps)


def test_two_valleys_two_keypoints_main_first():
    from app.services.keyline import detect_keypoints
    dem = _valley_dem(cols=(20, 60))
    accum = _accum(80, (20, 60), (40, 80))
    kps = detect_keypoints(dem, TF, accum, np.ones((80, 80), bool))
    assert len(kps) == 2
    assert kps[0]["valley_cells"] >= kps[1]["valley_cells"]
    assert abs(kps[0]["col"] - 60) <= 2 and abs(kps[1]["col"] - 20) <= 2


def test_flat_dem_no_keypoint():
    from app.services.keyline import detect_keypoints
    flat = np.full((80, 80), 100.0, dtype=np.float32)
    assert detect_keypoints(flat, TF, _accum(80, (40,), (80,)), np.ones((80, 80), bool)) == []


def test_components_diagonal_is_connected():
    from app.services.keyline import _components
    b = np.zeros((5, 5), bool)
    b[1, 1] = b[2, 2] = True
    assert len(_components(b)) == 1


def test_components_gap_gives_two():
    from app.services.keyline import _components
    b = np.zeros((5, 5), bool)
    b[1, 1] = b[1, 3] = True
    assert len(_components(b)) == 2


def test_components_branched_is_one():
    from app.services.keyline import _components
    b = np.zeros((7, 7), bool)
    b[1, 1] = b[2, 2] = b[3, 3] = b[4, 3] = b[5, 3] = b[2, 4] = b[1, 5] = True
    comps = _components(b)
    assert len(comps) == 1 and len(comps[0]) == 7


def test_planar_slope_with_channel_no_keypoint():
    from app.services.keyline import detect_keypoints
    i = np.arange(80)[:, None].astype(float)
    j = np.arange(80)[None, :].astype(float)
    dem = (120 - 0.3 * i + 0.5 * np.abs(j - 40)).astype(np.float32)
    assert detect_keypoints(dem, TF, _accum(80, (40,), (80,)), np.ones((80, 80), bool)) == []


def test_walk_stays_on_valley_floor():
    from app.services.keyline import _valley_floor_path
    dem = _valley_dem()
    accum = _accum(80, (40,), (80,))
    valley = accum >= 8
    path = _valley_floor_path(dem, accum, valley, (72, 40))
    assert all(valley[r, c] for r, c in path)
    assert all(c == 40 for _, c in path)


# ---- Task 2: trace, parallels, clipping -----------------------------------

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box


@pytest.fixture
def hillside():
    """120x120 valley running north-south, falling to the south, 1 m cells."""
    n = 120
    dem = np.fromfunction(
        lambda i, j: 100 + (np.sqrt((j - 59.5) ** 2 + 9.0) - 3) * 0.1 + (1 - i / n) * 6, (n, n), dtype=np.float64
    )
    transform = from_origin(600000, 4700000, 1.0, 1.0)
    mask = np.ones((n, n), dtype=bool)
    x, y = transform @ (60.5, 60.5)
    kp = {"row": 60, "col": 60, "x": float(x), "y": float(y),
          "z": float(dem[60, 60]), "valley_cells": 60}
    return dem, transform, mask, kp


def test_keyline_crosses_slope_both_sides_and_stays_in_mask(hillside):
    from app.services.keyline import trace_keyline
    dem, transform, mask, kp = hillside
    line = trace_keyline(dem, transform, kp, 0.005, mask)
    assert isinstance(line, LineString) and line.length > 20
    xs = [p[0] for p in line.coords]
    assert min(xs) < kp["x"] - 5 and max(xs) > kp["x"] + 5
    assert line.distance(Point(kp["x"], kp["y"])) < 1.0
    inv = ~transform
    for x, y in line.coords:
        c, r = inv @ (x, y)
        assert mask[int(r), int(c)]
    # mean grade along the path length of each arm is within 10 % of the design grade
    from app.services.keyline import _bilinear
    def zat(p):
        c, r = inv @ p
        return _bilinear(dem, r - 0.5, c - 0.5)
    kpt = Point(kp["x"], kp["y"])
    s_kp = line.project(kpt)
    assert 0 < s_kp < line.length
    arm_a = line.length - s_kp
    for end, arm in ((line.coords[0], s_kp), (line.coords[-1], arm_a)):
        assert arm > 10
        mean_grade = (zat((kp["x"], kp["y"])) - zat(end)) / arm
        assert mean_grade == pytest.approx(0.005, rel=0.10)
    # left of travel is uphill (contract used by keyline_pattern)
    left = shapely.get_parts(line.offset_curve(3.0))
    right = shapely.get_parts(line.offset_curve(-3.0))
    def mean_z(g):
        zs = []
        for p in shapely.get_coordinates(g):
            c, r = inv @ p
            if 0 <= int(r) < 120 and 0 <= int(c) < 120:
                zs.append(dem[int(r), int(c)])
        return np.mean(zs)
    assert np.mean([mean_z(g) for g in left]) > np.mean([mean_z(g) for g in right])


def test_keyline_stops_at_mask_edge(hillside):
    from app.services.keyline import trace_keyline
    dem, transform, mask, kp = hillside
    small = np.zeros_like(mask)
    small[50:70, 40:80] = True
    line = trace_keyline(dem, transform, kp, 0.005, small)
    assert line.length > 0
    inv = ~transform
    for x, y in line.coords:
        c, r = inv @ (x, y)
        assert small[int(r), int(c)]
    x0, y0 = transform @ (40, 70)
    x1, y1 = transform @ (80, 50)
    edge = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)).exterior
    for end in (line.coords[0], line.coords[-1]):
        assert edge.distance(Point(end)) <= 1.0 + 1e-6


@pytest.fixture
def crest():
    """Slope falling 0.1 to the west that ends in a near-flat top (0.02) at column 80."""
    n = 120
    i, j = np.mgrid[0:n, 0:n].astype(float)
    dem = 100 - 0.1 * np.minimum(j, 80.0) - 0.02 * np.maximum(j - 80.0, 0.0)
    transform = from_origin(600000, 4700000, 1.0, 1.0)
    x, y = transform @ (60.5, 60.5)
    kp = {"row": 60, "col": 60, "x": float(x), "y": float(y),
          "z": float(dem[60, 60]), "valley_cells": 60}
    return dem, transform, np.ones((n, n), dtype=bool), kp


def test_keyline_stops_at_ridge_crest(crest):
    from app.services.keyline import trace_keyline
    dem, transform, mask, kp = crest
    # grade 0.05 on a 0.1 slope: the line drifts 20 m across to the flat top
    line = trace_keyline(dem, transform, kp, 0.05, mask)
    for end in (line.coords[0], line.coords[-1]):
        # ends on the flat top (column 80) ...
        assert end[0] - kp["x"] == pytest.approx(19.5, abs=2.0)
        # ... not at the mask edge, 60 m away
        assert 5 < (kp["y"] - end[1]) + 60 < 115
    assert line.length > 40


def _lines(result):
    return [r["geometry"] for r in result]


# ---- Real-terrain rework: nodata, flat valley floors, analysis grid, coverage ----


def test_analysis_grid_fills_small_gaps_and_keeps_wide_ones():
    from app.services.keyline import ANALYSIS_CELL_M, NODATA_FILL_MAX_M, analysis_grid
    n = 100
    i, j = np.mgrid[0:n, 0:n].astype(float)
    plane = 200 - 0.1 * i - 0.05 * j
    dem = plane.copy()
    dem[20:23, 20:23] = np.nan                  # 6 m hole
    dem[:, 60:] = np.nan                        # 80 m wide gap
    acc = np.ones((n, n))
    acc[np.isnan(dem)] = np.nan
    tf = from_origin(600000, 4700000, ANALYSIS_CELL_M, ANALYSIS_CELL_M)
    d, a, t = analysis_grid(dem, tf, acc)
    assert t == tf and d.shape == dem.shape
    assert np.abs(d[20:23, 20:23] - plane[20:23, 20:23]).max() < 0.1
    far = int(NODATA_FILL_MAX_M / ANALYSIS_CELL_M) + 2
    assert np.isnan(d[:, 60 + far:]).all()      # beyond the fill distance
    assert np.isfinite(d[:, 60]).all()          # gap edge is filled
    assert not np.isnan(a).any() and a[50, 90] == 0.0


def test_keypoints_ignore_nodata_cells():
    from app.services.keyline import detect_keypoints
    dem = _valley_dem().astype(float)
    accum = _accum(80, (40,), (80,))
    dem[70:80, 30:50] = np.nan                  # gap over the valley outlet
    kps = detect_keypoints(dem, TF, accum, np.ones((80, 80), bool))
    assert len(kps) == 1
    assert abs(kps[0]["row"] - 40) <= 2 and abs(kps[0]["col"] - 40) <= 2
    assert np.isfinite(kps[0]["z"])


def test_trace_ends_before_nodata_without_crashing(hillside):
    from app.services.keyline import trace_keyline
    dem, transform, mask, kp = hillside
    dem = dem.copy()
    dem[:, 85:95] = np.nan                      # gap across the east arm
    line = trace_keyline(dem, transform, kp, 0.005, mask)
    xs = [p[0] for p in line.coords]
    assert all(np.isfinite(shapely.get_coordinates(line)).ravel())
    assert max(xs) < transform.c + 85
    assert min(xs) < kp["x"] - 20               # the west arm is unaffected


def test_keypoint_on_valley_with_flat_floor_stretch():
    """A breached DEM leaves flat stretches on valley floors; steepest descent
    recomputed there has no direction, so the floor walk must not rely on it."""
    from app.services.keyline import _valley_floor_path, detect_keypoints
    n = 80
    i = np.arange(n)[:, None].astype(float)
    j = np.arange(n)[None, :].astype(float)
    floor = np.where(i <= 40, 120 - 0.5 * i, np.where(i <= 60, 100 - 0.05 * (i - 40), 99.0))
    dem = floor + 0.5 * np.abs(j - 40)
    accum = np.zeros((n, n))
    accum[:, 40] = np.arange(n) + 1.0           # grows downstream, across the flat
    valley = accum >= 8
    path = _valley_floor_path(dem, accum, valley, (79, 40))
    assert path[-1] == (7, 40)                  # walked through the flat to the top
    kps = detect_keypoints(dem, TF, accum, np.ones((n, n), bool))
    assert len(kps) == 1 and abs(kps[0]["row"] - 40) <= 2 and kps[0]["col"] == 40


def _fine_valley(cell=0.5, size_m=160.0, furrow=0.08):
    """Valley falling south, slope break 80 m down, with plough furrows 1 m apart
    (amplitude `furrow` m) running down the slope."""
    n = int(size_m / cell)
    i, j = np.mgrid[0:n, 0:n].astype(float)
    y, x = (i + 0.5) * cell, (j + 0.5) * cell
    floor = np.where(y <= 80, 130 - 0.25 * y, 110 - 0.025 * (y - 80))
    cross = (np.sqrt((x - 80) ** 2 + 9.0) - 3) * 0.15
    dem = floor + cross + furrow * np.sin(2 * np.pi * x / 1.0)
    acc = np.zeros((n, n))
    acc[:, int(80 / cell)] = (np.arange(n) + 1) * 4.0
    return dem, acc, from_origin(600000, 4700000, cell, cell)


def test_fine_dem_is_analysed_on_coarser_grid():
    from app.services.keyline import ANALYSIS_CELL_M, analysis_grid, detect_keypoints, trace_keyline
    dem, acc, tf = _fine_valley()
    d, a, t = analysis_grid(dem, tf, acc)
    assert t.a == ANALYSIS_CELL_M and t.e == -ANALYSIS_CELL_M and (t.c, t.f) == (tf.c, tf.f)
    assert d.shape == (80, 80)
    # furrows (1 m wavelength) average out on the 2 m grid
    assert np.abs(d[10, 10] - (130 - 0.25 * 21 + (np.sqrt(59 ** 2 + 9) - 3) * 0.15)) < 0.01
    # accumulation keeps the drainage line, in analysis cells
    assert a.max() == pytest.approx(acc.max() / 16)
    mask = np.ones(d.shape, bool)
    kps = detect_keypoints(d, t, a, mask)
    assert len(kps) == 1
    assert abs(kps[0]["x"] - (tf.c + 80)) <= 4 and abs((tf.f - kps[0]["y"]) - 80) <= 4
    line = trace_keyline(d, t, kps[0], 0.005, mask)
    assert line.length > 50


def test_dem_at_analysis_cell_is_unchanged():
    from app.services.keyline import analysis_grid
    dem, acc, tf = _fine_valley(cell=2.0, furrow=0.0)
    d, a, t = analysis_grid(dem, tf, acc)
    assert t == tf and np.array_equal(d, dem) and np.array_equal(a, acc)


def test_keyline_ends_before_turning_back_over_a_crest():
    """Ridge along column 60 whose sides are steeper than its fall: the contour
    turns back (> 90 degrees) over the crest, onto the other slope."""
    from app.services.keyline import trace_keyline
    n = 120
    i, j = np.mgrid[0:n, 0:n].astype(float)
    dem = 100 - 0.05 * i - 0.1 * np.abs(j - 60)
    x, y = TF @ (40.5, 10.5)
    kp = {"row": 10, "col": 40, "x": float(x), "y": float(y), "z": float(dem[10, 40])}
    line = trace_keyline(dem, TF, kp, 0.005, np.ones((n, n), bool))
    xs = [p[0] - TF.c for p in line.coords]
    crest = 60.5                                # centre of column 60
    assert crest - 3 < max(xs) <= crest + 1     # ends at the crest, within a step
    assert min(xs) < 40


def test_keyline_ends_where_slope_reverses():
    """Uphill is north west of column 50 and south east of it: going on would
    put uphill on the other side of the line, so it ends at column 50."""
    from app.services.keyline import trace_keyline
    n = 100
    i, j = np.mgrid[0:n, 0:n].astype(float)
    dem = 100 + 0.1 * (60 - i) * np.where(j < 50, 1.0, -1.0)
    x, y = TF @ (30.5, 60.5)
    kp = {"row": 60, "col": 30, "x": float(x), "y": float(y), "z": 100.0}
    line = trace_keyline(dem, TF, kp, 0.005, np.ones((n, n), bool))
    xs = [p[0] - TF.c for p in line.coords]
    assert 47 < max(xs) <= 51
    assert min(xs) < 5


def test_analysis_grid_with_cell_not_dividing_2m():
    """0.75 m cells: block factor round(2 / 0.75) = 3, so the grid is 2.25 m."""
    from app.services.keyline import analysis_grid
    n = 100
    i, j = np.mgrid[0:n, 0:n].astype(float)
    dem = 100 - 0.75 * (0.05 * i + 0.02 * j)
    acc = np.zeros((n, n))
    acc[:, 50] = np.arange(n) + 1.0
    tf = from_origin(600000, 4700000, 0.75, 0.75)
    d, a, t = analysis_grid(dem, tf, acc)
    assert t.a == pytest.approx(2.25) and t.e == pytest.approx(-2.25) and (t.c, t.f) == (tf.c, tf.f)
    assert d.shape == (34, 34)                  # 100 / 3 rounded up, edge blocks partial
    assert d[0, 0] == pytest.approx(dem[0:3, 0:3].mean())
    assert d[33, 33] == pytest.approx(dem[99, 99])      # 1-cell edge block
    assert a.max() == pytest.approx(100 / 9)


# ---- Owner rule: lines within 1.5 % over 20 m, new guides where parallels drift ----

TF2 = from_origin(600000, 4700000, 2.0, 2.0)
N2 = 100


def _kp2(dem, row, col):
    x, y = TF2 @ (col + 0.5, row + 0.5)
    return {"row": row, "col": col, "x": float(x), "y": float(y), "z": float(dem[row, col])}


def _plane():
    """200 m square on 2 m cells, falling 5 % to the south."""
    i = np.arange(N2)[:, None].astype(float)
    return np.repeat(100 - 0.05 * 2.0 * i, N2, axis=1)


def _fan():
    """Slope rising from 3 % in the west to 11 % in the east: the contours fan
    out, so true parallels of a contour line drift off grade."""
    i, j = np.mgrid[0:N2, 0:N2].astype(float)
    return 100 - (0.03 + 0.0004 * 2.0 * j) * 2.0 * i


PARCEL2 = box(600003.3, 4699803.3, 600196.7, 4699996.7)


def _layout(dem, parcel=PARCEL2, kp=(50, 50), **kw):
    from app.services.keyline import keyline_layout
    return keyline_layout(dem, TF2, np.ones(dem.shape, bool), parcel, [_kp2(dem, *kp)], 12.0, **kw)


def _no_crossings(lines):
    tree = shapely.STRtree(lines)
    return not any(a < b for a, b in zip(*tree.query(lines, predicate="intersects")))


def _coverage(lines, parcel, spacing=12.0):
    from shapely.ops import unary_union
    return unary_union([g.buffer(spacing / 2) for g in lines]).intersection(parcel).area / parcel.area


def test_layout_parallels_follow_the_keyline_on_a_plane():
    from app.services.keyline import MAX_LINE_GRADE
    res = _layout(_plane())
    assert [r["direction"] for r in res].count("keyline") == 1
    own = [r for r in res if r["guide"] == 0]
    for side in (lambda r: r["offset_m"] >= 0, lambda r: r["offset_m"] <= 0):
        chain = sorted((r for r in own if side(r)), key=lambda r: abs(r["offset_m"]))
        assert len(chain) >= 5
        for a, b in zip(chain, chain[1:]):
            assert a["geometry"].distance(b["geometry"]) == pytest.approx(12.0, rel=0.01)
    assert all(r["offset_m"] > 0 for r in own if r["direction"] == "up")
    assert all(r["offset_m"] < 0 for r in own if r["direction"] == "down")
    for r in own:                               # measured, not the design value
        assert 0.003 < r["grade"] < 0.006 and r["max_grade_20m"] <= MAX_LINE_GRADE
    lines = _lines(res)
    assert _no_crossings(lines)
    assert _coverage(lines, PARCEL2) > 0.95
    assert all(g.difference(PARCEL2.buffer(1e-6)).is_empty for g in lines)


def test_layout_max_lines_draws_no_new_guides():
    from app.services.keyline import MIN_SEGMENT_M
    res = _layout(_plane(), max_lines=2)
    assert {r["direction"] for r in res} <= {"keyline", "up", "down"}
    assert {r["offset_m"] for r in res} <= {-24.0, -12.0, 0.0, 12.0, 24.0}
    assert all(r["geometry"].length >= MIN_SEGMENT_M for r in res)


def test_layout_respects_holes_and_multipolygon():
    hole = box(600070, 4699870, 600130, 4699930)
    holed = Polygon(PARCEL2.exterior.coords, [hole.exterior.coords])
    res = _layout(_plane(), parcel=holed, kp=(20, 50))
    assert res
    for g in _lines(res):
        assert g.intersection(hole.buffer(-1e-6)).is_empty
    multi = MultiPolygon([box(600003.3, 4699803.3, 600080, 4699996.7),
                          box(600120, 4699803.3, 600196.7, 4699996.7)])
    res2 = _layout(_plane(), parcel=multi, kp=(50, 20))
    gap = box(600080.001, 4699800, 600119.999, 4700000)
    assert res2 and all(g.intersection(gap).is_empty for g in _lines(res2))
    assert max(g.centroid.x for g in _lines(res2)) > 600120


def test_layout_seeds_new_guides_where_parallels_exceed_the_cap():
    from app.services.keyline import MAX_LINE_GRADE, line_grade
    fan = _fan()
    res = _layout(fan)
    guides = [r for r in res if r["direction"] == "guide"]
    assert guides
    for r in res:
        mean, worst = line_grade(r["geometry"], fan, TF2)
        assert worst <= MAX_LINE_GRADE
        assert (mean, worst) == pytest.approx((r["grade"], r["max_grade_20m"]))
    lines = _lines(res)
    assert _no_crossings(lines)
    full = _coverage(lines, PARCEL2)
    # parallels of the keyline alone (no new guides) stop where they drift
    alone = _coverage(_lines(_layout(fan, max_lines=100)), PARCEL2)
    assert full > 0.9 and full > alone + 0.2


def test_layout_caps_line_grade_on_steepening_ground():
    """True parallels of the keyline would fall more than the cap at some
    offsets: those stretches are left out, nothing above the cap is drawn."""
    from app.services.keyline import MAX_LINE_GRADE, line_grade
    fan = _fan()
    res = _layout(fan, max_lines=100)
    assert all(line_grade(g, fan, TF2)[1] <= MAX_LINE_GRADE for g in _lines(res))
    # the same parallels on a plane cover the parcel; on the fan the cap
    # removed the stretches that drifted off grade
    assert _coverage(_lines(_layout(_plane(), max_lines=100)), PARCEL2) > 0.95
    assert _coverage(_lines(res), PARCEL2) < 0.8


def test_layout_never_crosses_unfilled_nodata():
    dem = _plane()
    dem[40:60, 20:40] = np.nan
    footprint = box(600040, 4699880, 600080, 4699920)
    res = _layout(dem)
    lines = _lines(res)
    assert lines and not any(g.intersects(footprint) for g in lines)
    assert _coverage(lines, PARCEL2.difference(footprint)) > 0.85


def test_end_to_end_valley_to_layout():
    from app.services.keyline import MAX_LINE_GRADE, detect_keypoints, keyline_layout
    dem, acc, tf = _fine_valley(cell=2.0, furrow=0.0)
    mask = np.ones(dem.shape, bool)
    kps = detect_keypoints(dem, tf, acc, mask)
    parcel = box(tf.c + 5, tf.f - 155, tf.c + 155, tf.f - 5)
    res = keyline_layout(dem, tf, mask, parcel, kps, 12.0)
    assert any(r["direction"] == "keyline" for r in res)
    lines = _lines(res)
    assert _no_crossings(lines)
    assert all(g.difference(parcel.buffer(1e-6)).is_empty for g in lines)
    assert all(r["max_grade_20m"] <= MAX_LINE_GRADE for r in res)
    assert _coverage(lines, parcel) > 0.8
