"""End-to-end worker tests with mocked DEM + Orion (engine is real)."""
from unittest.mock import patch, MagicMock, AsyncMock

import numpy as np
import rasterio
import io


def _fake_dem_bytes(cols=60, rows=60):
    """A real DEM (slope) GeoTIFF in EPSG:4258 that the engine can process."""
    z = np.fromfunction(
        lambda i, j: 100 + abs(j - rows // 2) * 0.5 + i * 0.5,
        (rows, cols), dtype=np.float32,
    )
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=rows, width=cols, count=1,
        dtype="float32", crs="EPSG:4258",
        transform=rasterio.transform.from_origin(-1.645, 42.822, 0.0002, 0.0002),
    ) as dst:
        dst.write(z, 1)
    return buf.getvalue()


def _default_soil():
    """Return a default SoilContext for tests (matches OrionContextClient defaults)."""
    from app.services.orion_context_client import SoilContext
    return SoilContext()


def test_run_dem_pipeline_uploads_and_publishes():
    from app.workers.hydrology_worker import run_dem_pipeline
    fake_dem = _fake_dem_bytes()

    poly = {
        "type": "Polygon",
        "coordinates": [[
            [-1.645, 42.812], [-1.635, 42.812],
            [-1.635, 42.822], [-1.645, 42.822], [-1.645, 42.812],
        ]],
    }

    with patch("app.workers.hydrology_worker.DEMClient") as DEMC, \
         patch("app.workers.hydrology_worker.tile_service") as ts, \
         patch("app.workers.hydrology_worker.records_publish") as rp, \
         patch("app.workers.hydrology_worker._read_parcel_polygon",
               return_value=(poly, 5.0)), \
         patch("app.workers.hydrology_worker._reproject_to_utm",
               return_value=fake_dem), \
         patch("app.workers.hydrology_worker.OrionContextClient") as OCC, \
         patch("app.workers.hydrology_worker.extract_zonal_stats",
               side_effect=lambda z, *a: z):
        DEMC.return_value.fetch_dem.return_value = MagicMock()
        rp.publish_hydrology_record = AsyncMock()
        rp.publish_hydrology_zones = AsyncMock()
        occ_mock = MagicMock()
        occ_mock.get_soil_context.return_value = _default_soil()
        occ_mock.get_ndvi_mean.return_value = (0.4, "default")
        OCC.return_value.__enter__.return_value = occ_mock

        result = run_dem_pipeline("urn:ngsi-ld:AgriParcel:p1", "job-1", "t1")

    assert result["status"] == "done"
    assert rp.publish_hydrology_record.await_count == 1
    assert rp.publish_hydrology_zones.await_count == 1


def test_run_dem_pipeline_flat_dem_degrades():
    """A flat DEM (no relief) -> dataFidelity degraded_flat, not empty."""
    from app.workers.hydrology_worker import run_dem_pipeline
    flat_dem = _flat_dem_bytes()
    poly = {
        "type": "Polygon",
        "coordinates": [[
            [-1.645, 42.812], [-1.635, 42.812],
            [-1.635, 42.822], [-1.645, 42.822], [-1.645, 42.812],
        ]],
    }

    with patch("app.workers.hydrology_worker.DEMClient") as DEMC, \
         patch("app.workers.hydrology_worker.tile_service") as ts, \
         patch("app.workers.hydrology_worker.records_publish") as rp, \
         patch("app.workers.hydrology_worker._read_parcel_polygon",
               return_value=(poly, 5.0)), \
         patch("app.workers.hydrology_worker._reproject_to_utm",
               return_value=flat_dem), \
         patch("app.workers.hydrology_worker.OrionContextClient") as OCC, \
         patch("app.workers.hydrology_worker.extract_zonal_stats",
               side_effect=lambda z, *a: z):
        DEMC.return_value.fetch_dem.return_value = MagicMock()
        rp.publish_hydrology_record = AsyncMock()
        rp.publish_hydrology_zones = AsyncMock()
        occ_mock = MagicMock()
        occ_mock.get_soil_context.return_value = _default_soil()
        occ_mock.get_ndvi_mean.return_value = (0.4, "default")
        OCC.return_value.__enter__.return_value = occ_mock

        result = run_dem_pipeline("urn:ngsi-ld:AgriParcel:p1", "job-1", "t1")

    # record carries degraded_flat
    args = rp.publish_hydrology_record.await_args
    record = args.args[1] if args.args else args.kwargs.get("record")
    assert record["nkz:dataFidelity"]["value"] == "degraded_flat"


def _flat_dem_bytes():
    """Constant DEM -> degenerate flow accumulation."""
    z = np.full((40, 40), 100.0, dtype=np.float32)
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=40, width=40, count=1,
        dtype="float32", crs="EPSG:25830",
        transform=rasterio.transform.from_origin(600000, 4700000, 2.0, 2.0),
    ) as dst:
        dst.write(z, 1)
    return buf.getvalue()
