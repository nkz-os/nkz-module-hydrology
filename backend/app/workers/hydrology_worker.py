"""
NKZ Water Studio — RQ Worker

RQ worker entry point for the DEM pipeline. Uses GeoLibreEngine to run
fill, flow accumulation, stream extraction, slope, aspect, and TWI.

NOTE (geolibre-wasm 0.4.4): raster_streams_to_vector is skipped due to
d8_pointer crash. The pipeline uses run_dem_pipeline() which has this
workaround built in.
"""

import json
import logging
from typing import Optional

from app.config import get_settings
from app.services.geolibre_engine import GeoLibreEngine, GeoLibreError

logger = logging.getLogger(__name__)


def run_dem_pipeline(parcel_id: str, job_id: str) -> dict:
    """RQ worker entry point: full DEM pipeline for a parcel.

    Fase 0: synthetic DEM only. Real DEM cascade from Open-Meteo / Copernicus
    comes in Fase 1.

    Returns a dict with status summary.
    """
    logger.info("[%s] Starting DEM pipeline for parcel %s", job_id, parcel_id)

    dem = _fetch_dem(parcel_id)
    if not dem:
        raise RuntimeError(f"DEM unavailable for parcel {parcel_id}")

    eng = GeoLibreEngine()
    result = eng.run_dem_pipeline(dem)

    _upload_results(parcel_id, job_id, result)

    return {
        "status": "done",
        "parcel_id": parcel_id,
        "outputs": list(result.keys()),
        "sizes": {k: len(v) for k, v in result.items()},
    }


def _fetch_dem(parcel_id: str) -> Optional[bytes]:
    """Fase 0: synthetic DEM only. Fase 1: real DEM cascade."""
    logger.warning("Using synthetic DEM for parcel %s (Fase 0)", parcel_id)
    return _synthetic_dem()


def _upload_results(parcel_id: str, job_id: str, files: dict[str, bytes]):
    """Fase 0: log sizes. Fase 1: MinIO upload."""
    for name, data in files.items():
        logger.info("  [%s] %s: %d bytes", job_id, name, len(data))


def _synthetic_dem() -> bytes:
    """Generate 200x200 synthetic DEM for Fase 0 testing."""
    import numpy as np
    import rasterio
    import tempfile
    from rasterio.transform import from_origin

    size = 200
    dem = np.fromfunction(
        lambda i, j: 100 + abs(j - size // 2) * 0.5,
        (size, size), dtype=np.float32
    )
    np.random.seed(42)
    dem += np.random.rand(size, size).astype(np.float32) * 0.2

    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        with rasterio.open(
            tmp.name, "w", driver="GTiff",
            height=size, width=size, count=1, dtype="float32",
            crs="EPSG:25830",
            transform=from_origin(600000, 4700000, 1.0, 1.0),
        ) as dst:
            dst.write(dem, 1)
        with open(tmp.name, "rb") as f:
            return f.read()
