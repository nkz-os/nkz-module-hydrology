# NKZ Water Studio — Setup Guide

## 1. Prerequisites

- Python 3.11+
- Node.js 22+
- pnpm 9+
- Redis (for RQ background jobs)
- MinIO (for DEM storage)

## 2. Backend

```bash
cd backend
pip install -r requirements.txt
cp ../env.example .env  # or link to ../.env
# Edit .env — set REDIS_URL, MINIO_*, etc.
uvicorn app.main:app --reload --port 8000
```

## 3. Frontend

```bash
pnpm install
cp env.example .env
pnpm run dev
```

## 4. K8s Deployment

```bash
docker build -f backend/Dockerfile -t ghcr.io/nkz-os/hydrology-backend:v1.0.0 ./backend
docker push ghcr.io/nkz-os/hydrology-backend:v1.0.0
kubectl apply -f k8s/backend-deployment.yaml -n nekazari
```

## 5. Database Registration

```bash
psql -U postgres -d nekazari -f k8s/registration.sql
```
