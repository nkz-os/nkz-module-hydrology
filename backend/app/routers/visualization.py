"""PMTiles generation and flow data endpoints."""

import json
import logging

import boto3
from fastapi import APIRouter, HTTPException
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/visualization", tags=["viz"])


def get_flow_lines_geojson(parcel_id: str):
    """Get stream network GeoJSON from MinIO."""
    settings = get_settings()
    s3 = boto3.client("s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=f"pipelines/{parcel_id}/streams.geojson",
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return None


@router.get("/{parcel_id}/flows")
async def get_flows(parcel_id: str):
    """Get stream network as GeoJSON FeatureCollection."""
    data = get_flow_lines_geojson(parcel_id)
    if not data:
        raise HTTPException(status_code=404, detail="No flow data")
    return data


@router.get("/{parcel_id}/tiles/twi")
async def get_twi_tiles(parcel_id: str):
    """Get TWI PMTiles URL."""
    settings = get_settings()
    url = f"{settings.minio_public_url}/{settings.minio_bucket}/pmtiles/{parcel_id}/twi.pmtiles"
    return {"url": url}


@router.get("/{parcel_id}/kpis")
async def get_kpis(parcel_id: str):
    """Get scenario KPIs for parcel."""
    settings = get_settings()
    s3 = boto3.client("s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    try:
        resp = s3.get_object(
            Bucket=settings.minio_bucket,
            Key=f"scenarios/{parcel_id}/kpis.json",
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception:
        return {"baseline": {}, "intervention": {}}
