"""NKZ Water Studio — RQ Worker (Ronda 2.1: real DEM pipeline).

Reads the parcel polygon from Orion, fetches the DEM from eu-elevation
(service-to-service, no auth), reprojects to UTM, runs the geolibre engine,
uploads PMTiles/GeoJSON to MinIO (tenant-scoped), and publishes the
AgriParcelRecord + AgriParcelZone entities via the contract frozen in Ronda 2.2.

Stream threshold is PHYSICAL (1 ha) for consistency between 5m/25m resolutions.
Flat DEMs are detected and gracefully degraded (dataFidelity: degraded_flat).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import rasterio
from shapely.geometry import shape as shply_shape
from nkz_platform_sdk import OrionClient

from app.config import get_settings
from app.services.dem_client import DEMClient, DEMGrid, DEMUnavailable, resolution_for_area_ha
from app.services.entity_publisher import build_hydrology_record, build_hydrology_zones
from app.services.geolibre_engine import GeoLibreEngine
from app.services.utm import reproject_grid_to_utm
from app.services.weather_client import WeatherClient, WeatherUnavailable, ParcelWeather
from app.services.bucket_model import BucketModel
from app.services.scs_cn import runoff
from app.services.musle import musle_sediment, ls_from_slope, c_from_ndvi
from app.services.keyline import detect_keyline
from app.services.pond_score import pond_score
from app.services.orion_context_client import OrionContextClient
from app.services.zonal_stats import extract_zonal_stats
from app.services import tile_service, records_publish
from app.services.tile_service import parcel_short

logger = logging.getLogger(__name__)

_STREAM_AREA_M2 = 10_000.0  # 1 ha physical stream threshold (owner decision)
_DEG2M_APPROX = 111_320.0   # metres per degree (approximate, for buffer/area)


def run_dem_pipeline(parcel_id: str, job_id: str, tenant_id: str = "") -> dict:
    """RQ worker entry point: full DEM pipeline for a parcel.

    Returns a dict with status summary.
    """
    logger.info("[%s] DEM pipeline parcel=%s tenant=%s", job_id, parcel_id, tenant_id or "-")
    try:
        geometry, area_ha = _read_parcel_polygon(parcel_id, tenant_id)
    except Exception as exc:
        logger.exception("[%s] cannot read parcel polygon", job_id)
        raise

    resolution_m = resolution_for_area_ha(area_ha)
    bbox = _bbox_with_buffer(geometry, resolution_m, cells=2)

    client = DEMClient()
    try:
        grid = client.fetch_dem(bbox, resolution_m, tenant_id=tenant_id or None)
    except DEMUnavailable as exc:
        _publish_unavailable(parcel_id, tenant_id, geometry, str(exc))
        raise

    utm_dem = _reproject_to_utm(grid)

    eng = GeoLibreEngine()
    # Explicit engine steps with PHYSICAL stream threshold (1 ha), so the
    # network density is consistent across 5m/25m resolutions.  Replicates
    # geolibre_engine.run_dem_pipeline but passes our threshold.
    # Since geolibre-wasm 0.5.1, flow_accum_full_workflow --output_pointer
    # dumps the ESRI D8 pointer from the same breach pass as the accum
    # (no numpy workaround, no double-breaching divergence).
    threshold_cells = _STREAM_AREA_M2 / (resolution_m * resolution_m)
    breached = eng.breach_depressions(utm_dem)
    flow = eng._run("flow_accum_full_workflow",
        args=["--input_dem=/work/dem.tif", "--output=/work/accum.tif",
              "--output_pointer=/work/pntr.tif", "--esri_pntr=true",
              "--out_type=cells"],
        input_files={"dem.tif": utm_dem})
    accum = flow["accum.tif"]
    pntr = flow["pntr.tif"]  # ESRI, same breach pass as accum
    streams = eng.extract_streams(accum, threshold=threshold_cells)
    streams_vec = eng.streams_to_vector(streams, pntr)
    slope = eng.slope(breached)
    aspect = eng.aspect(breached)
    twi = eng.wetness_index(accum, slope)
    result = {
        "breached.tif": breached, "accum.tif": accum, "streams.tif": streams,
        "pntr.tif": pntr, "streams.geojson": streams_vec,
        "slope.tif": slope, "aspect.tif": aspect, "twi.tif": twi,
    }

    # Flat-terrain detection (PENDING.md / spec §3.6)
    data_fidelity = "ign_5m" if resolution_m <= 5.0 else "ign_25m"
    breached_arr = _read_raster(breached)
    if _is_flat(breached_arr):
        logger.warning("[%s] flat DEM -> degraded_flat", job_id)
        data_fidelity = "degraded_flat"

    # Upload outputs (tenant-scoped)
    _upload_results(parcel_id, tenant_id, result)

    # ── Weather data (Ronda 2.3 — platform meteo contract §8) ────────────
    # Fetch zonal weather stats from weather-map (internal service).
    # Data is stored in the AgriParcelRecord but NOT wired to agronomic
    # models yet (that is Ronda 2.5).
    weather = _fetch_weather(parcel_id, tenant_id, job_id)

    # Publish record + zones (contract 2.2, real data).
    # NOTE: watershedAreaHa is intentionally OMITTED — watershed delineation
    # needs a pour point (2.5).  build_hydrology_record omits missing keys
    # cleanly (never null).
    observed_at = datetime.now(timezone.utc).isoformat()
    metrics = _compute_metrics(result)
    if weather:
        _merge_weather_metrics(metrics, weather)

    # ── Orion Context (Ronda 2.6) ────────────
    with OrionContextClient(tenant_id or "platform") as orion_ctx:
        soil = orion_ctx.get_soil_context(parcel_id)
        ndvi_mean, ndvi_source = orion_ctx.get_ndvi_mean(parcel_id)
    logger.info(
        "[%s] Orion context: cn=%.0f ksat=%.1f ndvi=%.2f (%s) soil_source=%s",
        job_id, soil.cn, soil.ksat_mmh, ndvi_mean, ndvi_source, soil.source,
    )
    metrics["soilSource"] = soil.source
    metrics["vegetationSource"] = ndvi_source

    precip = weather.precipitation_mm if weather and weather.precipitation_mm is not None else 0.0
    eto = weather.eto_mm if weather and weather.eto_mm is not None else 0.0

    # Time of concentration (Kirpich) — needed by SCS-CN peak flow
    slope_mean = metrics.get("slopeMean", 5.0)
    stream_len = metrics.get("streamLengthM", 100.0)
    slope_frac = math.tan(math.radians(slope_mean)) if slope_mean > 0 else 0.001
    tc_h = (0.0195 * (stream_len ** 0.77) / (slope_frac ** 0.385)) / 60.0
    tc_h = max(0.1, min(tc_h, 24.0))  # clamp to sensible range

    # 1. SCS-CN
    run_mm, peak_m3s = runoff(precip, soil.cn, area_ha=area_ha, tc_h=tc_h)
    metrics["runoffMm"] = run_mm
    metrics["peakFlowM3s"] = peak_m3s

    # 2. Bucket Model
    bucket = BucketModel(ksat_mmh=soil.ksat_mmh, field_capacity_vv=soil.field_capacity_vv,
                         wilting_point_vv=soil.wilting_point_vv)
    b_res = bucket.step(precip, eto, cn=soil.cn)
    metrics["soilSaturationPct"] = b_res["saturation_pct"]

    # 3. MUSLE
    ls_fact = ls_from_slope(slope_mean)
    c_fact = c_from_ndvi(ndvi_mean)
    runoff_m3 = (run_mm / 1000.0) * area_ha * 10_000.0
    sediment = musle_sediment(runoff_m3, peak_m3s, soil.k_factor, ls_fact, c_fact)
    metrics["sedimentYieldTonnes"] = sediment

    # 4. Pond Viability
    try:
        earthwork = max(100.0, runoff_m3 * 0.5)
        ps = pond_score(
            catchment_yield_m3=runoff_m3,
            earthwork_m3=earthwork,
            reliability_pct=80.0,
            ksat_mmh=soil.ksat_mmh,
        )
        metrics["pondViability"] = ps["pondScore"]
    except Exception as e:
        logger.warning("[%s] pond_score failed: %s", job_id, e)

    # 5. Keyline Guide
    try:
        with rasterio.open(io.BytesIO(utm_dem)) as ds:
            utm_transform = ds.transform
        breached_arr = _read_raster(breached)
        accum_arr = _read_raster(accum)
        kl_res = detect_keyline(breached_arr, utm_transform, accum_arr)
        if kl_res and "properties" in kl_res:
            metrics["keylineGrade"] = kl_res["properties"].get("grade", 0.0)
    except Exception as e:
        logger.warning("[%s] keyline detect failed: %s", job_id, e)
    record = build_hydrology_record(
        tenant_id=tenant_id or "platform", parcel_id=parcel_id,
        geometry=geometry, observed_at=observed_at, metrics=metrics,
        dem_source="ign",
        data_fidelity=data_fidelity,
    )
    # ── Agronomic Models — Zonal (Ronda 2.6) ────────────
    zones_raw = _compute_zones(result)
    try:
        zones_raw = extract_zonal_stats(
            zones_raw, result["slope.tif"], result["twi.tif"], result["accum.tif"],
        )
        logger.info("[%s] zonal stats extracted for %d zones", job_id, len(zones_raw))
    except Exception as e:
        logger.warning("[%s] zonal stats extraction failed: %s", job_id, e)

    # Run agronomic models per zone — NEW BucketModel per zone (stateful!)
    try:
        for zone in zones_raw:
            z_slope = zone.get("slopeMean", slope_mean)
            z_area_ha = zone.get("areaHa", area_ha / max(len(zones_raw), 1))

            z_run_mm, z_peak_m3s = runoff(precip, soil.cn, area_ha=z_area_ha, tc_h=tc_h)
            zone["nkz:runoffMm"] = z_run_mm
            zone["nkz:peakFlowM3s"] = z_peak_m3s

            bucket_z = BucketModel(
                ksat_mmh=soil.ksat_mmh,
                field_capacity_vv=soil.field_capacity_vv,
                wilting_point_vv=soil.wilting_point_vv,
            )
            bz = bucket_z.step(precip, eto, cn=soil.cn)
            zone["nkz:soilSaturationPct"] = bz["saturation_pct"]

            z_slope_len = max(10.0, min(200.0, (z_area_ha * 10000.0) ** 0.5))
            z_ls = ls_from_slope(z_slope, slope_length_m=z_slope_len)
            z_runoff_m3 = (z_run_mm / 1000.0) * z_area_ha * 10000.0
            z_sed = musle_sediment(z_runoff_m3, z_peak_m3s, soil.k_factor, z_ls, c_fact)
            zone["nkz:sedimentYieldTonnes"] = z_sed

            try:
                z_ew = max(100.0, z_runoff_m3 * 0.5)
                z_ps = pond_score(z_runoff_m3, z_ew, 80.0, soil.ksat_mmh)
                zone["nkz:pondViability"] = z_ps["pondScore"]
            except Exception:
                pass

            zone["nkz:keylineGrade"] = metrics.get("keylineGrade", 0.0)

        logger.info("[%s] zonal models complete for %d zones", job_id, len(zones_raw))
    except Exception as e:
        logger.warning("[%s] zonal model run failed: %s", job_id, e)

    zones = build_hydrology_zones(
        tenant_id=tenant_id or "platform", parcel_id=parcel_id,
        observed_at=observed_at, zones=zones_raw,
    )
    asyncio.run(_publish(tenant_id, record, zones))
    return {"status": "done", "parcel_id": parcel_id,
            "dataFidelity": data_fidelity, "outputs": list(result.keys())}


def _fetch_weather(
    parcel_id: str, tenant_id: str, job_id: str,
) -> ParcelWeather | None:
    """Fetch zonal weather stats from weather-map (soft-fail).

    Weather is non-blocking: if weather-map is unreachable the DEM pipeline
    still completes.  The record simply won't carry meteo KPIs.
    """
    try:
        client = WeatherClient()
        pw = client.fetch_stats(parcel_id, tenant_id or "platform")
        logger.info(
            "[%s] weather: eto=%.2f precip=%.2f sm=%s",
            job_id,
            pw.eto_mm if pw.eto_mm is not None else -1,
            pw.precipitation_mm if pw.precipitation_mm is not None else -1,
            pw.soil_moisture,
        )
        return pw
    except WeatherUnavailable as exc:
        logger.warning("[%s] weather-map unavailable, proceeding without meteo: %s", job_id, exc)
        return None
    except Exception:
        logger.exception("[%s] unexpected error fetching weather", job_id)
        return None


def _merge_weather_metrics(metrics: dict, weather: ParcelWeather) -> None:
    """Merge weather KPIs into the metrics dict for the AgriParcelRecord.

    Keys match _RECORD_METRICS in entity_publisher.py.
    """
    if weather.eto_mm is not None:
        metrics["etoMm"] = weather.eto_mm
    if weather.precipitation_mm is not None:
        metrics["precipitationMm"] = weather.precipitation_mm
    if weather.temperature_avg is not None:
        metrics["temperatureAvg"] = weather.temperature_avg
    if weather.temperature_min is not None:
        metrics["temperatureMin"] = weather.temperature_min
    if weather.soil_moisture is not None:
        metrics["soilMoisture"] = weather.soil_moisture



# ── helpers ──────────────────────────────────────────────────────────────────

def _read_parcel_polygon(parcel_id: str, tenant_id: str) -> tuple[dict, float]:
    """Read AgriParcel.location polygon + area_ha from Orion."""
    orion = OrionClient(tenant_id)
    try:
        ent = asyncio.run(orion.get_entity(parcel_id))
    finally:
        asyncio.run(orion.close())
    loc = ent.get("location", {}).get("value")
    if not loc:
        raise RuntimeError(f"AgriParcel {parcel_id} has no location")
    area_ha = shply_shape(loc).area * (_DEG2M_APPROX ** 2) / 10_000.0
    return loc, area_ha


def _bbox_with_buffer(geometry: dict, resolution_m: float, cells: int = 2) -> tuple:
    """BBox of the parcel + N cells buffer (so flow-accum keeps context at border)."""
    poly = shply_shape(geometry)
    buf_deg = (cells * resolution_m) / _DEG2M_APPROX
    minx, miny, maxx, maxy = poly.bounds
    return (minx - buf_deg, miny - buf_deg, maxx + buf_deg, maxy + buf_deg)


def _reproject_to_utm(grid: DEMGrid) -> bytes:
    """DEMGrid (EPSG:4258 degrees) -> UTM GeoTIFF bytes (metric cellsize)."""
    arr = np.array(grid.elevations, dtype="float32")
    transform = rasterio.transform.from_origin(
        grid.origin_lon, grid.origin_lat,
        grid.pixel_size_deg, grid.pixel_size_deg,
    )
    buf = io.BytesIO()
    with rasterio.open(buf, "w", driver="GTiff", height=arr.shape[0],
                       width=arr.shape[1], count=1, dtype="float32",
                       crs="EPSG:4258", transform=transform) as dst:
        dst.write(arr, 1)
    return reproject_grid_to_utm(buf.getvalue(), grid.origin_lon, grid.origin_lat)


def _read_raster(tif_bytes: bytes) -> np.ndarray:
    with rasterio.open(io.BytesIO(tif_bytes)) as ds:
        return ds.read(1)


def _is_flat(arr: np.ndarray) -> bool:
    """Effectively flat terrain (< 1 m relief after breaching)."""
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return True
    return float(valid.max() - valid.min()) < 1.0


def _upload_results(parcel_id: str, tenant_id: str, result: dict) -> None:
    """Upload PMTiles + rasters + GeoJSON to MinIO (tenant-scoped)."""
    try:
        tile_service.generate_twi_pmtiles(
            parcel_id, tenant_id, result["twi.tif"],
        )
    except Exception:
        logger.exception("PMTiles upload failed")
    try:
        _put_geojson(parcel_id, tenant_id, result["streams.geojson"])
    except Exception:
        logger.exception("streams upload failed")
    # Ronda 2.6+: persist derived rasters for the design API endpoints
    for raster_name in ("breached.tif", "accum.tif", "slope.tif"):
        if raster_name in result:
            try:
                _put_raster(parcel_id, tenant_id, raster_name, result[raster_name])
            except Exception:
                logger.exception("%s upload failed", raster_name)


def _put_geojson(parcel_id: str, tenant_id: str, data: bytes) -> None:
    from app.services.s3 import get_s3_client
    settings = get_settings()
    key = tile_service.stream_network_key(parcel_id, tenant_id)
    get_s3_client().put_object(Bucket=settings.minio_bucket, Key=key,
                               Body=data, ContentType="application/geo+json")


def _put_raster(parcel_id: str, tenant_id: str, raster_name: str, data: bytes) -> None:
    from app.services.s3 import get_s3_client
    settings = get_settings()
    key = f"hydrology/{tenant_id}/{parcel_short(parcel_id)}/{raster_name}"
    get_s3_client().put_object(Bucket=settings.minio_bucket, Key=key,
                               Body=data, ContentType="image/tiff")


def _compute_metrics(result: dict) -> dict:
    """Scalar KPIs from the engine outputs.

    watershedAreaHa is intentionally NOT emitted — watershed delineation needs
    a pour point (2.5). build_hydrology_record omits missing keys cleanly.
    """
    twi = _read_raster(result["twi.tif"])
    slope = _read_raster(result["slope.tif"])
    streams = result["streams.geojson"]
    return {
        "twiMean": float(np.nanmean(twi)),
        "twiMax": float(np.nanmax(twi)),
        "slopeMean": float(np.nanmean(slope)),
        "streamLengthM": _stream_length_m(streams),
    }


def _stream_length_m(geojson_bytes: bytes) -> float:
    try:
        gj = json.loads(geojson_bytes)
    except Exception:
        return 0.0
    total = 0.0
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            total += math.hypot(x2 - x1, y2 - y1)  # UTM metres
    return total


def _compute_zones(result: dict) -> list[dict]:
    """5 TWI quintile zones from the TWI raster (masked to parcel)."""
    twi = _read_raster(result["twi.tif"]).ravel()
    twi = twi[np.isfinite(twi)]
    if twi.size == 0:
        return []
    labels = ["twi-very-low", "twi-low", "twi-medium", "twi-high", "twi-very-high"]
    quintiles = np.quantile(twi, [0.2, 0.4, 0.6, 0.8])
    zones = []
    for i, lab in enumerate(labels):
        lo = -np.inf if i == 0 else quintiles[i - 1]
        hi = np.inf if i == 4 else quintiles[i]
        mask = (twi > lo) & (twi <= hi)
        if mask.any():
            zones.append({
                "zone_id": lab, "geometry": {},
                "twiMean": float(twi[mask].mean()),
                "twiRange": f"{lo:.1f}-{hi:.1f}", "areaHa": 0.0,
                "pixelCount": int(mask.sum()),
            })
    return zones


async def _publish(tenant_id: str, record: dict, zones: list[dict]) -> None:
    await records_publish.publish_hydrology_record(tenant_id, record)
    await records_publish.publish_hydrology_zones(tenant_id, zones)


def _publish_unavailable(parcel_id: str, tenant_id: str, geometry: dict, msg: str) -> None:
    observed_at = datetime.now(timezone.utc).isoformat()
    record = build_hydrology_record(
        tenant_id=tenant_id or "platform", parcel_id=parcel_id,
        geometry=geometry, observed_at=observed_at, metrics={},
        dem_source="ign", data_fidelity="unavailable",
    )
    try:
        asyncio.run(records_publish.publish_hydrology_record(tenant_id or "platform", record))
    except Exception:
        logger.exception("could not publish unavailable record")
