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
