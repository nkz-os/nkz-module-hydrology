"""Tests for design_generator service."""
import io
import numpy as np
import rasterio

from app.services.design_generator import (
    generate_keyline_parallels,
    extract_contour_at_elevation,
    find_slope_inflections,
)


def _fake_dem(shape=(80, 80), transform=None):
    """Synthetic valley DEM."""
    if transform is None:
        transform = rasterio.transform.from_origin(600000, 4700000, 2.0, 2.0)
    # Valley running N-S in the center
    xs = np.arange(shape[1], dtype=np.float32)
    center = shape[1] / 2
    z = 100 + 0.5 * np.abs(xs - center) + 0.1 * np.arange(shape[0])[:, None]
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=shape[0], width=shape[1],
                       count=1, dtype="float32", crs="EPSG:25830",
                       transform=transform) as dst:
        dst.write(z.astype(np.float32), 1)
    return buf.getvalue(), transform, z


class TestGenerateKeylineParallels:
    def test_returns_requested_number_of_lines(self):
        dem_bytes, transform, dem = _fake_dem()
        # Keyline: horizontal line across the valley at row 40
        keyline_coords = [[600000 + i * 2, 4700000 - 80] for i in range(40)]
        result = generate_keyline_parallels(
            dem_bytes, keyline_coords, spacing_m=10, n_lines=3, grade=0.005
        )
        assert "primary" in result
        assert "parallels" in result
        assert len(result["parallels"]) == 6  # 3 up + 3 down

    def test_parallels_are_offset(self):
        dem_bytes, transform, dem = _fake_dem()
        keyline_coords = [[600000 + i * 2, 4700000 - 80] for i in range(40)]
        result = generate_keyline_parallels(
            dem_bytes, keyline_coords, spacing_m=10, n_lines=1, grade=0.005
        )
        assert len(result["parallels"]) == 2  # 1 up + 1 down
        # Check they're different from primary
        up_line = result["parallels"][0]["geometry"]["coordinates"]
        assert up_line != keyline_coords


class TestContourExtraction:
    def test_returns_contour_lines(self):
        dem_bytes, transform, dem = _fake_dem()
        # Sample elevation at center of DEM
        mid_elev = float(dem[40, 40])
        lines = extract_contour_at_elevation(dem_bytes, mid_elev, max_length_m=200)
        assert len(lines) > 0
        for line in lines:
            assert line["type"] == "LineString"
            assert len(line["coordinates"]) >= 2

    def test_empty_when_elevation_out_of_range(self):
        dem_bytes, transform, dem = _fake_dem()
        lines = extract_contour_at_elevation(dem_bytes, 9999.0, max_length_m=200)
        assert lines == []


class TestSlopeInflections:
    def test_finds_inflection_in_valley_profile(self):
        """Synthetic V-shaped valley has one inflection at the bottom."""
        xs = np.linspace(0, 100, 50)
        zs = np.abs(xs - 50) * 0.5  # V shape
        points = find_slope_inflections(xs, zs, threshold_deg=2.0)
        # Should find the inflection at xs ≈ 50 (valley bottom)
        assert len(points) >= 1

    def test_flat_profile_returns_empty(self):
        xs = np.linspace(0, 100, 50)
        zs = np.full(50, 100.0)
        points = find_slope_inflections(xs, zs, threshold_deg=2.0)
        assert points == []
