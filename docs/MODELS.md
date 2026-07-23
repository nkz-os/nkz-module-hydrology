# Hydrology Models Reference

Reference for the numerical models in NKZ Water Studio. Inputs come from the
DEM cascade (eu-elevation), per-parcel weather (weather-map), and soil/NDVI
context (Orion-LD). Outputs land on the per-tenant `AgriParcelRecord` /
`AgriParcelZone` entities unless noted.

## 1. Terrain (geolibre engine)

- **Breaching** of depressions, then **D8 flow accumulation** (ESRI pointer,
  single breach pass) and **stream extraction** at a physical 1 ha threshold
  (consistent across 5 m / 25 m resolutions).
- **Slope** (degrees) and **TWI** = `ln(α / tan(β))` (specific catchment area /
  slope). Flat DEMs (`< 1 m` relief) degrade to `dataFidelity: degraded_flat`.

## 2. Runoff — SCS-CN

`runoff(precip_mm, cn, area_ha, tc_h)` → runoff depth (mm) + peak flow (m³/s).
Time of concentration via **Kirpich**: `tc = 0.0195 · L^0.77 / S^0.385`. CN and
Ksat come from the parcel's `AgriSoil` context (or defaults).

## 3. Sediment — MUSLE (event)

`musle_sediment(runoff_m3, peak_m3s, K, LS, C)` → tonnes/event. LS factor from
slope (%) and slope length; C factor from NDVI (more cover → less erosion).

## 4. Soil moisture — bucket model

Single-step balance on (precip, ET₀) parametrized by Ksat, field capacity and
wilting point → `soilSaturationPct`. Stateful across calls in principle;
currently one step per pipeline run.

## 5. Pond viability — `pond_score`

Scores catchment yield vs earthwork, reliability and Ksat → `pondScore` +
`isViable`. Compliance (below) is added to the same response.

## 6. Zonal analysis

5 TWI-quintile zones per parcel. Boundaries emitted as `twiRange` strings
(`-inf-6.0`, …) so `extract_zonal_stats` reproduces the exact pixel masks.
**Zone geometry**: each zone's pixel mask is polygonized
(`rasterio.features.shapes`), unioned + simplified (metric tolerance), and
reprojected UTM → WGS84 so the viewer renders polygons. Per-zone runoff /
sediment / saturation / pond viability computed independently.

## 7. Scenario comparison (on demand)

`/parcels/{id}/scenarios` — `scenario_engine.simulate_baseline` vs
`simulate_intervention`, computed live from the latest record + the parcel's
current capture designs.

- **Captured water** = Σ `nkz:capacity` over the parcel's pond designs.
- **Sediment retained** = baseline sediment × (captured / total runoff)
  (physical heuristic — capturing water traps sediment).
- **Earthwork** ≈ captured volume; **investment** = earthwork × 8 €/m³.

> **ASSUMPTION:** the pipeline computes *event*-based runoff (SCS-CN design
> storm); the comparison uses it as the reference volume. Valid as a *relative*
> baseline-vs-intervention assessment. Surfaced to the caller via `assumptions`.

## 8. Compliance (`compliance.py`)

- **Water permit** — CHX basin thresholds (`PERMIT_THRESHOLDS_M3`, m³/year):
  Ebro/Minho-Sil 7000, Duero/Tajo/Guadiana/Guadalquivir/Cantábrico 5000,
  Segura/Júcar 3000, default 5000. Volumes above the threshold require a permit.
- **Breach risk** — `low` / `medium` / `high` from volume, local slope (3×3
  finite difference on the DEM) and downstream exposure.
- **ASSUMPTION:** downstream exposure defaults to `False` (no infrastructure
  layer bundled); basin auto-detection from coordinates needs a CHX polygon
  asset (deferred) — the caller selects the basin.

## 9. Alerts (`alerts.py`, reactive)

`evaluate_alerts(saturation, precip, ndvi, slope)`:

- **Saturation excess (Dunne)** — `critical` if saturation > 80% and precip >
  10 mm; `warning` if > 60% and precip > 20 mm.
- **Infiltration excess (Hortonian)** — `warning` if NDVI < 0.3 (bare soil) and
  precip > 25 mm.

> **ASSUMPTION (2A):** NDVI defaults to 0.5 (not persisted on the record);
> precip is the observed value used as the forecast proxy. Predictive
> (forecast-driven) alerts + 24 h saturation hysteresis + persistent `Alert`
> entities are Phase 2B (need the weather-map forecast endpoint, Redis state for
> the API pod, and webhook notification signing).
