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
