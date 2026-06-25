"""Tests for ZonalStatsExtractor."""
import io
import numpy as np
import rasterio

from app.services.zonal_stats import extract_zonal_stats


def _synthetic_raster(shape=(40, 40), values=None, pixel_size=2.0):
    """Create a synthetic GeoTIFF raster in EPSG:25830."""
    if values is None:
        values = np.random.default_rng(42).uniform(1, 45, shape).astype(np.float32)
    else:
        values = np.asarray(values, dtype=np.float32)
    buf = io.BytesIO()
    transform = rasterio.transform.from_origin(600000, 4700000, pixel_size, pixel_size)
    with rasterio.open(buf, "w", driver="GTiff", height=shape[0], width=shape[1],
                       count=1, dtype="float32", crs="EPSG:25830",
                       transform=transform) as dst:
        dst.write(values, 1)
    return buf.getvalue()


class TestZonalStatsExtractor:
    def test_returns_same_number_of_zones(self):
        zones = [
            {"zone_id": "twi-very-low",  "twiMean": 4.0, "twiRange": "-inf-6.0"},
            {"zone_id": "twi-low",       "twiMean": 8.0, "twiRange": "6.0-10.0"},
            {"zone_id": "twi-medium",    "twiMean": 14.0, "twiRange": "10.0-18.0"},
            {"zone_id": "twi-high",      "twiMean": 22.0, "twiRange": "18.0-26.0"},
            {"zone_id": "twi-very-high", "twiMean": 28.0, "twiRange": "26.0-inf"},
        ]
        slope = _synthetic_raster()
        twi = _synthetic_raster()
        accum = _synthetic_raster()
        result = extract_zonal_stats(zones, slope, twi, accum)
        assert len(result) == 5

    def test_adds_slope_mean_per_zone(self):
        zones = [
            {"zone_id": "twi-very-low", "twiMean": 4.0, "twiRange": "-inf-6.0"},
        ]
        slope = _synthetic_raster()
        twi = _synthetic_raster()
        accum = _synthetic_raster()
        result = extract_zonal_stats(zones, slope, twi, accum)
        assert "slopeMean" in result[0]
        assert isinstance(result[0]["slopeMean"], float)
        assert result[0]["slopeMean"] > 0

    def test_adds_area_ha(self):
        zones = [
            {"zone_id": "twi-very-low", "twiMean": 4.0, "twiRange": "-inf-6.0"},
        ]
        slope = _synthetic_raster()
        twi = _synthetic_raster()
        accum = _synthetic_raster()
        result = extract_zonal_stats(zones, slope, twi, accum)
        assert "areaHa" in result[0]
        assert result[0]["areaHa"] > 0

    def test_steeper_slope_in_low_twi_zone(self):
        """Ridge (low TWI) should have higher slope than valley (high TWI)."""
        z_twi = np.zeros((40, 40), dtype=np.float32)
        z_twi[:, :20] = 5.0   # ridge
        z_twi[:, 20:] = 25.0  # valley
        twi_buf = _synthetic_raster(values=z_twi)

        z_slope = np.zeros((40, 40), dtype=np.float32)
        z_slope[:, :20] = 25.0  # steep ridge
        z_slope[:, 20:] = 3.0   # gentle valley
        slope_buf = _synthetic_raster(values=z_slope)

        accum_buf = _synthetic_raster()
        zones = [
            {"zone_id": "twi-low", "twiMean": 5.0, "twiRange": "-inf-10.0"},
            {"zone_id": "twi-high", "twiMean": 25.0, "twiRange": "10.0-inf"},
        ]
        result = extract_zonal_stats(zones, slope_buf, twi_buf, accum_buf)
        ridge = next(z for z in result if z["zone_id"] == "twi-low")
        valley = next(z for z in result if z["zone_id"] == "twi-high")
        assert ridge["slopeMean"] > valley["slopeMean"]

    def test_empty_zones_returns_empty_list(self):
        slope = _synthetic_raster()
        twi = _synthetic_raster()
        accum = _synthetic_raster()
        result = extract_zonal_stats([], slope, twi, accum)
        assert result == []
