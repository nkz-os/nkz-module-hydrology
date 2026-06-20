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

The backend exposes endpoints under `/api/v1/hydrology/`:

| Path | Description |
|------|-------------|
| `GET /health` | Kubernetes probe |
| `POST /analyze/watershed` | Compute watershed boundaries |
| `POST /analyze/flow-accumulation` | Compute flow accumulation |
| `GET /jobs/` | List background jobs |
| `GET /jobs/{id}` | Get job status |
| `POST /setup/parcel/{id}` | Activate hydrology for a parcel |
| `DELETE /setup/parcel/{id}` | Deactivate hydrology for a parcel |

## Deploy

See [SETUP.md](SETUP.md) and the platform deployment guide.
