# NKZ Water Studio

Hydrology module for the Nekazari platform — DEM analysis, hydrological
modeling, water-harvesting design, regulatory compliance and runoff-risk alerts
for precision agriculture.

Built as a **Module Federation 2.0 remote** (frontend) with a **FastAPI + RQ**
backend (async DEM pipeline).

> **Status:** feature-complete, pre-production hardening. The DEM pipeline,
> agronomic models, design tools, scenarios, compliance and reactive alerts are
> wired end-to-end; persistent Alert entities + predictive (forecast-driven)
> alerts are pending (Phase 2B).

## What it does

For a selected `AgriParcel`, the module:

1. **Analyzes terrain** — downloads high-res elevation (eu-elevation cascade),
   computes flow direction/accumulation, stream network, slope and the
   **Topographic Wetness Index (TWI)**.
2. **Models hydrology** — SCS-CN runoff, Kirpich time-of-concentration, MUSLE
   sediment yield, a soil-moisture bucket model, and pond-viability scoring,
   fed by per-parcel weather (weather-map) and soil/NDVI context (Orion-LD).
3. **Designs interventions** — keyline, pond siting (with compliance), swales,
   check dams; CRUD + GeoJSON/GPX/KML export.
4. **Compares scenarios** — baseline vs intervention (water captured, sediment
   retained, earthwork, investment, autonomy), on demand from the latest record
   + current designs.
5. **Checks compliance** — CHX basin water-permit thresholds + breach-risk class
   on every pond score.
6. **Surfaces alerts** — saturation-excess (Dunne) / infiltration-excess
   (Hortonian) runoff risk, evaluated on demand.

## Architecture

```
Browser (MF2 remote)
  └─ slots: map-layer (TWI overlay, flows, zones, designs) + context-panel + layer-toggle
        └─ /api/v1/hydrology/*  (api-gateway: auth + tenant + HMAC)

Backend (FastAPI)
  ├─ /analyze/{parcel}  ──► RQ worker (hydrology-processing)
  │     DEM cascade → reproject UTM → geolibre engine (breach, flow accum,
  │       streams, slope, TWI) → zonal zones (polygon geometry) →
  │       SCS-CN + MUSLE + bucket + pond_score + keyline →
  │       publish AgriParcelRecord + AgriParcelZone (Orion-LD) + MinIO rasters
  └─ sync endpoints: designs CRUD/export, zones, summary, scenarios, alerts
```

**Data layers:** Orion-LD (per-tenant `AgriParcelRecord`, `AgriParcelZone`,
`nkz:WaterStorage`, `nkz:OpenChannelFlow`); MinIO (rasters, streams GeoJSON);
no direct DB writes for telemetry.

See [docs/MODELS.md](docs/MODELS.md) for the model reference.

## API

All endpoints under `/api/v1/hydrology/`, proxied by the platform api-gateway
(JWT + tenant + HMAC). The module does not validate JWT itself.

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/healthz` · `/readyz` | Liveness / readiness (Redis) | none |
| `POST` | `/analyze/{parcel_id}` | Enqueue DEM pipeline → `{job_id}` | gateway |
| `GET` | `/jobs/{job_id}` | Poll job status/result | gateway |
| `GET` | `/visualization/{parcel_id}/overlay/twi` | TWI PNG overlay (presigned) + bounds | gateway |
| `GET` | `/visualization/{parcel_id}/flows` | Stream network GeoJSON | gateway |
| `POST` | `/design/keyline/generate` | Keypoint + keyline + parallels | gateway |
| `POST` | `/design/pond/score` | Pond viability **+ compliance** | gateway |
| `POST` | `/design/swale/suggest` | Swale contour suggestions | gateway |
| `POST` | `/design/check-dam/suggest` | Check-dam locations | gateway |
| `GET` · `POST` | `/design` | List / create design entities | gateway |
| `GET` · `PUT` · `DELETE` | `/design/{design_id}` | Read / update / delete | gateway |
| `GET` | `/design/{design_id}/export` | GeoJSON / GPX / KML | gateway |
| `GET` | `/parcels/{parcel_id}/zones` | AgriParcelZone zonal KPIs (+ geometry) | gateway |
| `GET` | `/parcels/{parcel_id}/summary` | Latest record → flat KPIs | gateway |
| `GET` | `/parcels/{parcel_id}/scenarios` | Baseline vs intervention (on demand) | gateway |
| `GET` | `/parcels/{parcel_id}/alerts` | Active runoff-risk alerts (on demand) | gateway |
| `POST` | `/internal/setup-parcel` | Parcel activation (entity-manager) | X-Internal-Service-Secret |
| `POST` | `/webhooks/fiware-sensors` | DeviceMeasurement notification (log-only) | none |

## Development

```bash
pnpm install
cp env.example .env          # VITE_PROXY_TARGET, REDIS_URL, etc.
cd backend && pip install -r requirements.txt && cd ..
cd backend && uvicorn app.main:app --reload --port 8000   # API
rq worker hydrology-processing --url "$REDIS_URL"          # worker (separate)
pnpm run dev                                                # frontend (port 5003)
```

## Deploy

Module repo `k8s/` are **templates** — production values (image SHA, domains)
live in `gitops-config/overlays/modules/hydrology/` and are synced by ArgoCD.
Frontend publishes via OIDC on push to `main`; backend deploys on a gitops SHA
bump. See [SETUP.md](SETUP.md).
