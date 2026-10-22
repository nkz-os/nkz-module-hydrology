"""Task 10 — domain formula fixes: cos(lat) area + slope degrees→percent."""
import math
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


def test_parcel_area_uses_cos_lat_correction():
    """0.01°x0.01° square at lat 43 → cos(lat)-corrected area within 1%."""
    from app.workers.hydrology_worker import _read_parcel_polygon, _DEG2M_APPROX

    poly = {
        "type": "Polygon",
        "coordinates": [[
            [-1.645, 42.995], [-1.635, 42.995],
            [-1.635, 43.005], [-1.645, 43.005], [-1.645, 42.995],
        ]],
    }
    ent = {"location": {"value": poly}}

    with patch("app.workers.hydrology_worker.OrionClient") as OC:
        inst = OC.return_value
        inst.get_entity = AsyncMock(return_value=ent)
        inst.close = AsyncMock()
        _, area_ha = _read_parcel_polygon("urn:p1", "t1")

    expected = (0.01 * 0.01) * (_DEG2M_APPROX ** 2) * math.cos(math.radians(43.0)) / 10_000.0
    assert area_ha == pytest.approx(expected, rel=0.01)
    # Sanity: must be materially below the un-corrected (cos=1) figure.
    uncorrected = (0.01 * 0.01) * (_DEG2M_APPROX ** 2) / 10_000.0
    assert area_ha < uncorrected * 0.8


def test_slope_deg_to_pct_conversion():
    """Slope raster is in DEGREES; LS factor expects PERCENT (10° → 17.63%)."""
    from app.workers.hydrology_worker import _slope_deg_to_pct

    assert _slope_deg_to_pct(10.0) == pytest.approx(17.63, abs=0.01)
    assert _slope_deg_to_pct(0.0) == pytest.approx(0.0, abs=1e-9)
    # A degree value must NOT be passed through unchanged.
    assert _slope_deg_to_pct(10.0) != pytest.approx(10.0, abs=0.5)
