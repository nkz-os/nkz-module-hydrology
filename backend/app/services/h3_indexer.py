"""
H3 indexer: convert TWI raster to H3 hexagons with mean TWI per cell.
"""

import numpy as np
import h3
from rasterio.transform import xy
from typing import Optional


def raster_to_h3_twi(
    twi: np.ndarray,
    transform,
    resolution: int = 9,
    nodata: Optional[float] = None,
) -> dict[str, float]:
    """Aggregate TWI raster to H3 hexagons at given resolution.

    Args:
        twi: 2D TWI array
        transform: rasterio Affine transform
        resolution: H3 resolution (9 = ~0.5km², 10 = ~0.06km²)
        nodata: Value to ignore

    Returns:
        dict mapping hex_id -> mean TWI value
    """
    ny, nx = twi.shape
    hex_values: dict[str, list[float]] = {}

    # Sample every 2nd pixel for speed on large rasters
    step = max(1, min(nx, ny) // 100)

    for y in range(0, ny, step):
        for x in range(0, nx, step):
            val = twi[y, x]
            if nodata is not None and (np.isnan(val) or val == nodata):
                continue
            lon, lat = xy(transform, y, x)
            hex_id = h3.latlng_to_cell(lat, lon, resolution)
            if hex_id not in hex_values:
                hex_values[hex_id] = []
            hex_values[hex_id].append(float(val))

    result = {}
    for hex_id, values in hex_values.items():
        result[hex_id] = sum(values) / len(values)

    return result


def twi_to_risk_class(twi_mean: float) -> str:
    """Classify TWI into risk classes."""
    if twi_mean < 6:
        return "low"
    elif twi_mean < 10:
        return "moderate"
    elif twi_mean < 14:
        return "high"
    else:
        return "very_high"
