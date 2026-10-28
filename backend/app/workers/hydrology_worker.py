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
import dataclasses
import io
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import rasterio
from shapely.geometry import shape as shply_shape
from nkz_platform_sdk import OrionClient, SyncOrionClient

from app.config import get_settings
from app.services.dem_client import DEMClient, DEMGrid, DEMUnavailable, resolution_for_area_ha
from app.services.lidar_dem import LidarAsset, fetch_dtm_bytes, find_latest_lidar_asset, lidar_target_cellsize
from app.services.entity_publisher import build_hydrology_record, build_hydrology_zones
from app.services.geolibre_engine import GeoLibreEngine
from app.services.utm import reproject_grid_to_utm
from app.services.weather_client import DailyWater, WeatherClient, WeatherUnavailable, ParcelWeather
from app.services import design_cache
from app.services.design_rain import DesignDepth, design_depth_24h
from app.services.design_storm import SUBDAILY_SHAPE_SOURCE, alternating_block_hyetograph, design_storm_response
from app.services.parcel_settings import ParcelSettings, load_settings
from app.services.retention import RetentionResult, simulate_retention
from app.services.scenario_compute import fetch_parcel_designs
from app.services.bucket_model import BucketModel
from app.services.scs_cn import runoff
from app.services.musle import musle_sediment, ls_from_slope, c_from_ndvi
from app.services.keyline import detect_keyline
from app.services.pond_score import pond_score
from app.services.orion_context_client import OrionContextClient
from app.services.zonal_stats import extract_zonal_stats
from app.services import tile_service, records_publish
from app.logging_setup import configure_logging
from app.services.tile_service import parcel_short

logger = logging.getLogger(__name__)

# RQ configures only its own "rq.worker" logger.
configure_logging(get_settings().log_level)

_STREAM_AREA_M2 = 10_000.0  # 1 ha physical stream threshold (owner decision)
_DEG2M_APPROX = 111_320.0   # metres per degree (approximate, for buffer/area)


def _slope_deg_to_pct(slope_deg: float) -> float:
    """Convert a slope in DEGREES (geolibre raster contract) to PERCENT.

    ``ls_from_slope`` expects rise/run percent, while the engine slope raster
    (and the Kirpich tc block) work in degrees. e.g. 10° → 17.63%.
    """
    return math.tan(math.radians(slope_deg)) * 100.0


def run_dem_pipeline(parcel_id: str, job_id: str, tenant_id: str = "") -> dict:
    """RQ worker entry point: full DEM pipeline for a parcel.

    DEM source priority (cross-module contract 2026-09-02):
    1. LiDAR DTM (0.5 m) discovered via Orion DigitalAsset for the parcel
    2. eu-elevation raster (5 m / 25 m WCS) — legacy path

    Returns a dict with status summary.
    """
    logger.info("[%s] DEM pipeline parcel=%s tenant=%s", job_id, parcel_id, tenant_id or "-")
    try:
        geometry, area_ha = _read_parcel_polygon(parcel_id, tenant_id)
    except Exception as exc:
        logger.exception("[%s] cannot read parcel polygon", job_id)
        raise

    dem_source = "ign"
    utm_dem = None

    # ── 1. LiDAR DTM (cross-module: discovery via Orion, bytes via S3) ────
    lidar_asset: LidarAsset | None = None
    try:
        lidar_asset = asyncio.run(
            find_latest_lidar_asset(tenant_id or "platform", parcel_id)
        )
    except Exception as exc:
        logger.warning("[%s] LiDAR asset discovery failed: %s", job_id, exc)
    if lidar_asset is not None:
        try:
            dtm_bytes = fetch_dtm_bytes(lidar_asset)
            centroid = shply_shape(geometry).centroid
            cellsize = lidar_target_cellsize(area_ha)
            utm_dem = reproject_grid_to_utm(
                dtm_bytes, centroid.x, centroid.y, cellsize_m=cellsize
            )
            dem_source = "lidar"
            logger.info(
                "[%s] LiDAR DTM %s: %d bytes, cellsize=%s",
                job_id, lidar_asset.asset_id, len(dtm_bytes), cellsize or "native",
            )
        except Exception as exc:
            logger.warning(
                "[%s] LiDAR DTM fetch/reproject failed — fallback eu-elevation: %s",
                job_id, exc,
            )
            utm_dem = None

    # ── 2. eu-elevation WCS fallback ─────────────────────────────────────
    if utm_dem is None:
        resolution_m = resolution_for_area_ha(area_ha)
        bbox = _bbox_with_buffer(geometry, resolution_m, cells=2)
        client = DEMClient()
        try:
            grid = client.fetch_dem(bbox, resolution_m, tenant_id=tenant_id or None)
        except DEMUnavailable as exc:
            _publish_unavailable(parcel_id, tenant_id, geometry, str(exc))
            raise
        utm_dem = _reproject_to_utm(grid)

    # Actual cellsize from the UTM raster (drives stream threshold + fidelity)
    with rasterio.open(io.BytesIO(utm_dem)) as ds:
        resolution_m = float(abs(ds.transform.a))

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
    if dem_source == "lidar":
        data_fidelity = "lidar_05m" if resolution_m < 1.0 else "lidar_2m"
    else:
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
    metrics["parcelAreaHa"] = round(area_ha, 4)
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

    # 1. Runoff and peak flow in the parcel's calculation mode
    settings_ = load_settings(tenant_id or "platform", parcel_id)
    design = _design_inputs(parcel_id, tenant_id or "platform", settings_, soil, area_ha, job_id)
    metrics.update(design["record"])
    run_mm, peak_m3s = _mode_runoff(design, soil.cn, area_ha, tc_h)
    if run_mm is not None:
        metrics["runoffMm"] = run_mm
    if peak_m3s is not None:
        metrics["peakFlowM3s"] = peak_m3s

    # 2. Bucket Model
    bucket = BucketModel(ksat_mmh=soil.ksat_mmh, field_capacity_vv=soil.field_capacity_vv,
                         wilting_point_vv=soil.wilting_point_vv)
    b_res = bucket.step(precip, eto, cn=soil.cn)
    metrics["soilSaturationPct"] = b_res["saturation_pct"]

    # 3. MUSLE
    ls_fact = ls_from_slope(_slope_deg_to_pct(slope_mean))
    c_fact = c_from_ndvi(ndvi_mean)
    runoff_m3 = (run_mm / 1000.0) * area_ha * 10_000.0 if run_mm is not None else None
    if runoff_m3 is not None and peak_m3s is not None:
        metrics["sedimentYieldTonnes"] = musle_sediment(runoff_m3, peak_m3s, soil.k_factor, ls_fact, c_fact)

    # 4. Pond Viability
    if runoff_m3 is not None:
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
        dem_source=dem_source,
        data_fidelity=data_fidelity,
    )
    # ── Agronomic Models — Zonal (Ronda 2.6) ────────────
    zones_raw = _compute_zones(result, geometry)
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

            z_run_mm, z_peak_m3s = _mode_runoff(design, soil.cn, z_area_ha, tc_h)
            if z_run_mm is not None:
                zone["nkz:runoffMm"] = z_run_mm
            if z_peak_m3s is not None:
                zone["nkz:peakFlowM3s"] = z_peak_m3s

            bucket_z = BucketModel(
                ksat_mmh=soil.ksat_mmh,
                field_capacity_vv=soil.field_capacity_vv,
                wilting_point_vv=soil.wilting_point_vv,
            )
            bz = bucket_z.step(precip, eto, cn=soil.cn)
            zone["nkz:soilSaturationPct"] = bz["saturation_pct"]

            if z_run_mm is not None:
                z_runoff_m3 = (z_run_mm / 1000.0) * z_area_ha * 10000.0
                if z_peak_m3s is not None:
                    z_slope_len = max(10.0, min(200.0, (z_area_ha * 10000.0) ** 0.5))
                    z_ls = ls_from_slope(_slope_deg_to_pct(z_slope), slope_length_m=z_slope_len)
                    zone["nkz:sedimentYieldTonnes"] = musle_sediment(
                        z_runoff_m3, z_peak_m3s, soil.k_factor, z_ls, c_fact)
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
    """Parcel weather for the record (soft-fail, never blocks the DEM pipeline).

    Temperatures and soil moisture come from weather-map's zonal stats; rain and
    ET0 of the last closed day from weather-api's daily series. Either source may
    be missing: the record then simply lacks those KPIs.
    """
    tenant = tenant_id or "platform"
    client = WeatherClient()
    pw: ParcelWeather | None = None
    try:
        pw = client.fetch_stats(parcel_id, tenant)
    except WeatherUnavailable as exc:
        logger.warning("[%s] weather-map unavailable, proceeding without its stats: %s", job_id, exc)
    except Exception:
        logger.exception("[%s] unexpected error fetching weather-map stats", job_id)

    day = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    try:
        precip, eto = client.fetch_daily_water(parcel_id, tenant, day)
    except WeatherUnavailable as exc:
        logger.warning("[%s] daily rain unavailable, no precipitation for the record: %s", job_id, exc)
        precip = eto = None
    except Exception:
        logger.exception("[%s] unexpected error fetching daily rain", job_id)
        precip = eto = None

    if pw is None and precip is None and eto is None:
        return None
    if pw is None:
        pw = ParcelWeather(date=day.isoformat(), temperature_avg=None, temperature_min=None,
                           eto_mm=None, precipitation_mm=None, soil_moisture=None,
                           fidelity="parcel_weather")
    pw = dataclasses.replace(
        pw, date=day.isoformat(), precipitation_mm=precip,
        eto_mm=eto if eto is not None else pw.eto_mm,
    )
    logger.info(
        "[%s] weather %s: eto=%s precip=%s sm=%s",
        job_id, pw.date, pw.eto_mm, pw.precipitation_mm, pw.soil_moisture,
    )
    return pw


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



# ── calculation modes ────────────────────────────────────────────────────────

_HISTORY_YEARS = 30  # target length of the rain history (last full years)


class _DesignNotAvailable(Exception):
    """The history cannot support the design figures; never cached."""


def _history_to_json(history: list[DailyWater]) -> list[list]:
    return [[d.day.isoformat(), d.precip_mm, d.et0_mm] for d in history]


def _history_from_json(rows: list[list]) -> list[DailyWater]:
    from datetime import date
    return [DailyWater(date.fromisoformat(r[0]), r[1], r[2]) for r in rows]


def _design_inputs(
    parcel_id: str, tenant_id: str, settings: ParcelSettings, soil, area_ha: float, job_id: str,
) -> dict:
    """Mode-specific design figures from the rain history, cached per key.

    Returns ``{"mode", "status", "record", "hyetograph", "season_rain_mm"}``. When the
    history is missing or too short ``status`` is ``not_available`` with the reason in
    ``record``: nothing is estimated, the terrain results are still published.
    """
    mode = settings.mode
    record: dict = {"calculationMode": mode}
    if mode == "storm":
        record["returnPeriodYears"] = settings.return_period_years
    out: dict = {"mode": mode, "status": "not_available", "record": record,
                 "hyetograph": None, "season_rain_mm": None}
    last_full_year = datetime.now(timezone.utc).year - 1

    def _fetch() -> list[DailyWater]:
        try:
            return WeatherClient().fetch_daily_history(
                parcel_id, tenant_id, last_full_year - _HISTORY_YEARS + 1, last_full_year)
        except WeatherUnavailable as exc:
            raise _DesignNotAvailable(f"rain history unavailable: {exc}") from exc

    def _unavailable(reason: str) -> dict:
        logger.warning("[%s] design rain not available (%s): %s", job_id, mode, reason)
        record["designRainStatus"] = "not_available"
        record["designRainReason"] = reason
        return out

    try:
        if mode == "storm":
            def _compute() -> dict:
                depth = design_depth_24h(_fetch(), settings.return_period_years)
                if depth.status != "ok":
                    raise _DesignNotAvailable(depth.reason or "design depth not available")
                return dataclasses.asdict(depth)

            cached = design_cache.get_or_compute(
                tenant_id, parcel_id, mode, settings.return_period_years, last_full_year, _compute)
            depth = DesignDepth(**cached)
            record.update({
                "designRainStatus": "ok",
                "designRainMm": depth.depth_mm,
                "designRainCiLowMm": depth.ci_low_mm,
                "designRainCiHighMm": depth.ci_high_mm,
                "designRainLowConfidence": depth.low_confidence,
                "designRainSource": f"{depth.source}; {SUBDAILY_SHAPE_SOURCE}",
            })
            out["hyetograph"] = alternating_block_hyetograph(depth.depth_mm)
        else:
            def _compute() -> dict:
                return {"history": _history_to_json(_fetch())}

            cached = design_cache.get_or_compute(
                tenant_id, parcel_id, mode, settings.return_period_years, last_full_year, _compute)
            designs = fetch_parcel_designs(SyncOrionClient(tenant_id), parcel_id)
            res = simulate_retention(_history_from_json(cached["history"]), soil, designs, area_ha)
            if res.status != "ok":
                raise _DesignNotAvailable(res.reason or "retention not available")
            record.update({
                "designRainStatus": "ok",
                "designRainSource": "reanalysis",
                "retentionStoredM3": res.median.stored_m3,
                "retentionSummerDays": res.median.summer_days_above_threshold,
                "retentionDryStoredM3": res.dry.stored_m3,
                "retentionDrySummerDays": res.dry.summer_days_above_threshold,
            })
            out["season_rain_mm"] = res.median.season_rain_mm
    except _DesignNotAvailable as exc:
        return _unavailable(str(exc))
    out["status"] = "ok"
    return out


def _mode_runoff(design: dict, cn: float, area_ha: float, tc_h: float) -> tuple[float | None, float | None]:
    """``(runoff_mm, peak_m3s)`` for the calculation mode; ``None`` when not available.

    Storm: design hyetograph through the unit hydrograph. Retention: SCS-CN depth of the
    median year's season rain; no peak flow (not meaningful for a seasonal total).
    """
    if design["status"] != "ok":
        return None, None
    if design["mode"] == "storm":
        return design_storm_response(design["hyetograph"], cn, area_ha, tc_h)
    return runoff(design["season_rain_mm"], cn, area_ha=area_ha, tc_h=tc_h)[0], None


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_parcel_polygon(parcel_id: str, tenant_id: str) -> tuple[dict, float]:
    """Read AgriParcel.location polygon + area_ha from Orion."""
    orion = OrionClient(tenant_id)

    async def _get():
        try:
            return await orion.get_entity(parcel_id)
        finally:
            # Close on the SAME event loop that issued the request — the
            # httpx/httpcore anyio backend binds to the running loop, so a
            # separate asyncio.run(orion.close()) raises "Event loop is
            # closed".
            await orion.close()

    ent = asyncio.run(_get())
    loc = ent.get("location", {}).get("value")
    if not loc:
        raise RuntimeError(f"AgriParcel {parcel_id} has no location")
    # Degrees² → m²: the longitude degree shrinks by cos(lat), so the area
    # of a lat/lon polygon must be scaled by cos(centroid_lat). Without it the
    # area is overestimated ~37% at lat 43°N (feeds DEM resolution, SCS-CN
    # peak flow, runoff volume and MUSLE).
    shp = shply_shape(loc)
    centroid_lat = shp.centroid.y
    area_ha = shp.area * (_DEG2M_APPROX ** 2) * math.cos(math.radians(centroid_lat)) / 10_000.0
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
    """Band 1 as float, nodata cells as NaN so means and maxima skip them."""
    with rasterio.open(io.BytesIO(tif_bytes)) as ds:
        arr = ds.read(1).astype("float64")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan
        return arr


def _is_flat(arr: np.ndarray) -> bool:
    """Effectively flat terrain (< 1 m relief after breaching)."""
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return True
    return float(valid.max() - valid.min()) < 1.0


def _upload_results(parcel_id: str, tenant_id: str, result: dict) -> None:
    """Upload rasters + GeoJSON to MinIO (tenant-scoped).

    TWI visualization uses the PNG ground-overlay (overlay.py), not PMTiles —
    PMTiles generation was removed (compute with no consumer).
    """
    try:
        _put_geojson(parcel_id, tenant_id, result["streams.geojson"])
    except Exception:
        logger.exception("streams upload failed")
    # Ronda 2.6+: persist derived rasters for the design API endpoints
    for raster_name in ("breached.tif", "accum.tif", "slope.tif", "twi.tif"):
        if raster_name not in result:
            logger.warning("%s missing from pipeline result; not uploaded", raster_name)
            continue
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
    """Total stream length in metres; the network is stored in lon/lat (WGS84)."""
    from pyproj import Geod

    try:
        gj = json.loads(geojson_bytes)
    except Exception:
        return 0.0
    geod = Geod(ellps="WGS84")
    total = 0.0
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        lons, lats = zip(*[(c[0], c[1]) for c in coords])
        total += geod.line_length(lons, lats)
    return total


# One zone is published per broker request, and the broker refuses bodies over
# 1 MB; a quarter of that leaves room for the attributes and keeps the layer light.
MAX_ZONE_GEOMETRY_BYTES = 256 * 1024
# 6 decimals of a degree is ~0.1 m, finer than any DEM cell used here.
_COORD_DECIMALS = 6
_MAX_SIMPLIFY_STEPS = 8


def _round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, _COORD_DECIMALS) for c in coords]
    return [_round_coords(c) for c in coords]


def _broker_geometry(geom) -> dict:
    """GeoJSON the broker's geo index accepts: valid polygons on a 1e-6 degree grid.

    Simplification and plain rounding can leave self-crossing rings, which the
    index refuses; snapping with set_precision keeps the output valid. Parts that
    collapse to nothing are dropped. Returns {} when nothing is left.
    """
    import shapely
    from shapely.geometry import MultiPolygon, mapping

    snapped = shapely.set_precision(shapely.make_valid(geom), 10 ** -_COORD_DECIMALS)
    # make_valid may return a collection mixing polygons with lines or points.
    pieces = []
    for part in shapely.get_parts(snapped):
        pieces.extend(shapely.get_parts(part) if part.geom_type == "MultiPolygon" else [part])
    parts = [p for p in pieces if p.geom_type == "Polygon" and not p.is_empty and p.area > 0]
    if not parts:
        return {}
    out = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    geometry = mapping(out)
    # Coordinates are already on the grid; rounding only trims float noise.
    return {"type": geometry["type"], "coordinates": _round_coords(geometry["coordinates"])}


def _bounded_zone_geometry(merged, crs, res_m: float, parcel_geometry: dict | None) -> dict:
    """WGS84 geometry of a zone, clipped to the parcel, no larger than the budget.

    The tolerance starts at one cell and doubles until the polygon fits; the zone
    statistics come from the raster masks, so only the drawn outline coarsens.
    Returns {} (zone kept, no outline) when even the coarsest outline is too big.
    """
    import shapely
    from rasterio.warp import transform_geom
    from shapely.geometry import shape as shp_shape, mapping

    tolerance = res_m
    for _ in range(_MAX_SIMPLIFY_STEPS):
        simplified = merged.simplify(tolerance=tolerance, preserve_topology=False)
        if simplified.is_empty:
            return {}
        zone = shp_shape(transform_geom(crs, "EPSG:4326", mapping(simplified)))
        # Clip to the parcel boundary so zones never bleed outside.
        if parcel_geometry:
            try:
                zone = shapely.make_valid(zone).intersection(shp_shape(parcel_geometry))
            except Exception:
                pass
        if zone.is_empty:
            return {}
        geometry = _broker_geometry(zone)
        if not geometry:
            return {}
        if len(json.dumps(geometry)) <= MAX_ZONE_GEOMETRY_BYTES:
            return geometry
        tolerance *= 2
    logger.warning("zone outline over %d bytes even at %.1f m tolerance; published without it",
                   MAX_ZONE_GEOMETRY_BYTES, tolerance / 2)
    return {}


def _compute_zones(result: dict, parcel_geometry: dict | None = None) -> list[dict]:
    """5 TWI quintile zones WITH real polygon geometry.

    Boundaries are emitted as ``twiRange`` strings (e.g. ``-inf-6.0``) so
    ``extract_zonal_stats`` can reproduce the exact same pixel masks for
    area/slope stats. Geometry is built from those same masks (consistency),
    unioned + simplified in UTM, then reprojected to WGS84 for the broker
    (every consumer — Cesium, GPX/KML, GIS-routing — expects lon/lat).
    Finally each zone is clipped to the parcel polygon so TWI cells never bleed
    into the surrounding buffer.
    """
    from rasterio.features import shapes
    from shapely.geometry import shape as shp_shape
    from shapely.ops import unary_union

    with rasterio.open(io.BytesIO(result["twi.tif"])) as ds:
        twi = ds.read(1)
        transform = ds.transform
        crs = ds.crs
        res_m = max(abs(transform.a), abs(transform.e))
        nodata = ds.nodata

    valid = np.isfinite(twi)
    if nodata is not None:
        valid &= twi != nodata
    flat = twi[valid]
    if flat.size == 0:
        return []
    quintiles = np.quantile(flat, [0.2, 0.4, 0.6, 0.8])
    labels = ["twi-very-low", "twi-low", "twi-medium", "twi-high", "twi-very-high"]
    zones = []
    for i, lab in enumerate(labels):
        lo = -np.inf if i == 0 else float(quintiles[i - 1])
        hi = np.inf if i == 4 else float(quintiles[i])
        mask = valid & (twi > lo) & (twi <= hi)
        count = int(mask.sum())
        if count == 0:
            continue
        # Polygonize the zone mask in UTM, union + simplify (metric tolerance),
        # then reproject to WGS84. A raw per-pixel polygonization would emit
        # thousands of tiny rings; unary_union + simplify collapses them.
        geometry: dict = {}
        polys = [
            shp_shape(g)
            for g, v in shapes(mask.astype("uint8"), mask=mask, transform=transform)
            if v == 1
        ]
        if polys:
            geometry = _bounded_zone_geometry(unary_union(polys), crs, res_m, parcel_geometry)
        zones.append({
            "zone_id": lab,
            "geometry": geometry,
            "twiMean": float(twi[mask].mean()),
            "twiRange": f"{lo:.1f}-{hi:.1f}",
            "areaHa": round(count * res_m * res_m / 1e4, 4),
            "pixelCount": count,
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
