"""Tests for H3 indexer."""

import numpy as np
import pytest
from rasterio.transform import from_origin
from unittest.mock import patch


@pytest.fixture
def sample_twi():
    """20x20 TWI raster with a wet zone in center."""
    twi = np.ones((20, 20), dtype=np.float32) * 5.0
    twi[8:12, 8:12] = 15.0  # wet zone
    transform = from_origin(600000, 4700000, 10.0, 10.0)
    return twi, transform


def test_raster_to_h3_twi_returns_dict(sample_twi):
    from app.services.h3_indexer import raster_to_h3_twi
    twi, transform = sample_twi
    result = raster_to_h3_twi(twi, transform, src_crs="EPSG:25830", resolution=9)
    assert isinstance(result, dict)
    assert len(result) > 0
    for hex_id, mean_val in result.items():
        assert isinstance(hex_id, str)
        assert hex_id.startswith("8")  # H3 hex IDs start with 8 at res 9
        assert isinstance(mean_val, float)


def test_raster_to_h3_ignores_nodata(sample_twi):
    from app.services.h3_indexer import raster_to_h3_twi
    twi, transform = sample_twi
    twi[0, 0] = -9999
    result = raster_to_h3_twi(twi, transform, src_crs="EPSG:25830", nodata=-9999)
    assert len(result) > 0


def test_twi_to_risk_class():
    from app.services.h3_indexer import twi_to_risk_class
    assert twi_to_risk_class(4) == "low"
    assert twi_to_risk_class(8) == "moderate"
    assert twi_to_risk_class(12) == "high"
    assert twi_to_risk_class(16) == "very_high"
