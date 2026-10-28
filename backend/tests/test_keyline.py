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

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box


@pytest.fixture
def hillside():
    """120x120 valley running north-south, falling to the south, 1 m cells."""
    n = 120
    dem = np.fromfunction(
        lambda i, j: 100 + abs(j - 60) * 0.1 + (1 - i / n) * 6, (n, n), dtype=np.float64
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
    # elevation falls ~grade per metre away from the valley on both ends
    z0 = kp["z"]
    for end in (line.coords[0], line.coords[-1]):
        c, r = inv @ end
        d = math.hypot(end[0] - kp["x"], end[1] - kp["y"])
        assert dem[int(r), int(c)] < z0
        assert abs((z0 - dem[int(r), int(c)]) / d - 0.005) < 0.003
    # left of travel is uphill (contract used by keyline_pattern)
    left = line.offset_curve(3.0)
    right = line.offset_curve(-3.0)
    def mean_z(g):
        zs = []
        for p in g.coords:
            c, r = inv @ p
            if 0 <= int(r) < 120 and 0 <= int(c) < 120:
                zs.append(dem[int(r), int(c)])
        return np.mean(zs)
    assert mean_z(left) > mean_z(right)


def test_keyline_stops_at_mask_edge(hillside):
    from app.services.keyline import trace_keyline
    dem, transform, mask, kp = hillside
    small = np.zeros_like(mask)
    small[50:70, 40:80] = True
    line = trace_keyline(dem, transform, kp, 0.005, small)
    inv = ~transform
    for x, y in line.coords:
        c, r = inv @ (x, y)
        assert small[int(r), int(c)]


@pytest.fixture
def arc():
    return LineString([(0, 100), (50, 110), (100, 112), (150, 108), (200, 98)])


def _lines(result):
    return [r["geometry"] for r in result]


def test_pattern_spacing_respected(arc):
    from app.services.keyline import keyline_pattern
    parcel = box(0, 0, 200, 220)
    res = keyline_pattern([arc], 12.0, parcel)
    ups = sorted((r for r in res if r["direction"] == "up"), key=lambda r: r["offset_m"])
    assert len(ups) >= 3
    for a, b in zip(ups, ups[1:]):
        assert a["geometry"].distance(b["geometry"]) == pytest.approx(12.0, rel=0.01)
    offs = sorted(r["offset_m"] for r in res)
    assert offs[0] < 0 < offs[-1] and 0.0 in offs
    assert all(r["grade"] == 0.005 for r in res)


def test_pattern_lines_inside_parcel(arc):
    from app.services.keyline import keyline_pattern
    parcel = Polygon([(10, 20), (190, 30), (170, 200), (20, 190)])
    res = keyline_pattern([arc], 10.0, parcel)
    total = sum(g.length for g in _lines(res))
    inside = sum(g.intersection(parcel.buffer(1e-6)).length for g in _lines(res))
    assert total > 0 and inside / total == pytest.approx(1.0)


def test_pattern_no_crossings(arc):
    from app.services.keyline import keyline_pattern
    other = LineString([(0, 60), (100, 140), (200, 70)])
    res = keyline_pattern([arc, other], 9.0, box(0, 0, 200, 220))
    lines = _lines(res)
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            assert not lines[i].intersects(lines[j])
    assert res[0]["geometry"].equals(arc.intersection(box(0, 0, 200, 220)))


def test_pattern_drops_short_segments(arc):
    from app.services.keyline import MIN_SEGMENT_M, keyline_pattern
    parcel = box(0, 0, 200, 220)
    res = keyline_pattern([arc], 10.0, parcel)
    assert all(g.length >= MIN_SEGMENT_M for g in _lines(res))
    # a parcel corner that leaves only a tiny piece of a line gives nothing
    corner = box(0, 99, 3, 101)
    assert keyline_pattern([arc], 10.0, corner) == []
    # max_lines per side
    capped = keyline_pattern([arc], 10.0, parcel, max_lines=2)
    assert len(capped) <= 5


def test_pattern_respects_holes_and_multipolygon(arc):
    from app.services.keyline import keyline_pattern
    hole = box(70, 80, 130, 140)
    holed = Polygon(box(0, 0, 200, 220).exterior.coords, [hole.exterior.coords])
    res = keyline_pattern([arc], 8.0, holed)
    assert res
    for g in _lines(res):
        assert g.intersection(hole.buffer(-1e-6)).is_empty
        assert g.length >= 1
    assert any(g.distance(hole) < 1e-6 for g in _lines(res))

    a, b = box(0, 0, 80, 220), box(120, 0, 200, 220)
    multi = MultiPolygon([a, b])
    res2 = keyline_pattern([arc], 8.0, multi)
    gap = box(80.001, 0, 119.999, 220)
    for g in _lines(res2):
        assert g.intersection(gap).is_empty
    xs = [g.centroid.x for g in _lines(res2)]
    assert min(xs) < 80 and max(xs) > 120
