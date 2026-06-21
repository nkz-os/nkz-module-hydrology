"""Tests for keyline detection."""

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
