# NKZ Water Studio

Hydrology module for the Nekazari platform — watershed delineation, DEM analysis, and hydrological modeling for precision agriculture.

Built as a **Module Federation 2.0 remote** with a FastAPI backend.

## Quick start

```bash
cd nkz-module-hydrology
pnpm install
cp env.example .env
# Edit .env — set VITE_PROXY_TARGET, REDIS_URL, etc.
```

## Structure

```
nkz-module-hydrology/
├── src/
│   ├── Module.tsx              # defineModule({...})
│   ├── App.tsx                 # Main page component
│   ├── main.tsx                # Dev-only entry (Vite)
│   ├── slots/index.ts          # Host slot declarations
│   └── locales/{en,es}.json    # i18n bundles
├── backend/
│   ├── app/
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── main.py             # FastAPI create_app() factory
│   │   ├── api/
│   │   │   ├── __init__.py     # Main router + sub-router includes
│   │   │   ├── analyze.py      # Watershed, flow accumulation
│   │   │   ├── jobs.py         # RQ background job lifecycle
│   │   │   └── setup.py        # Parcel activation/deactivation
│   │   ├── middleware/         # JWT auth, tenant extraction
│   │   └── common/             # NGSI-LD headers, tenant utils
│   └── requirements.txt
├── k8s/
│   ├── backend-deployment.yaml
│   └── registration.sql
└── .github/workflows/build-push.yml
```

## Development

```bash
# Install frontend deps
pnpm install

# Install backend deps
cd backend && pip install -r requirements.txt && cd ..

# Run backend
cd backend && uvicorn app.main:app --reload --port 8000

# Run frontend (in another terminal)
pnpm run dev
```

## API

All endpoints live under `/api/v1/hydrology/` and are proxied by the platform
api-gateway (which validates JWT and injects tenant + HMAC headers). The module
does **not** validate JWT itself.

> Status: **beta** — only the DEM pipeline is wired end-to-end (Fase 0: synthetic
> DEM; real DEM cascade + MinIO upload arrive in the next phase).

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/healthz` | Liveness probe | none |
| `GET` | `/readyz` | Readiness (Redis) | none |
| `POST` | `/analyze/{parcel_id}` | Enqueue DEM pipeline job → `{job_id}` | gateway + HMAC |
| `GET` | `/jobs/{job_id}` | Poll job status/result | gateway + HMAC |
| `GET` | `/visualization/{parcel_id}/tiles/twi` | TWI PMTiles URL | gateway + HMAC |
| `GET` | `/visualization/{parcel_id}/tiles/risk` | Risk PMTiles URL | gateway + HMAC |
| `GET` | `/visualization/{parcel_id}/flows` | Stream network GeoJSON | gateway + HMAC |
| `GET` | `/visualization/{parcel_id}/flows/check` | Flow data existence | gateway + HMAC |
| `GET` | `/visualization/{parcel_id}/kpis` | Scenario KPIs | gateway + HMAC |
| `POST` | `/internal/setup-parcel` | Parcel activation (called by entity-manager) | X-Internal-Service-Secret |

## Deploy

See [SETUP.md](SETUP.md) and the platform deployment guide.
