"""Shared boto3 S3/MinIO client. Single place that normalizes the endpoint URL
(avoids the http://http:// double-prefix bug when minio_endpoint already has a scheme).
"""

import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings


def get_s3_client():
    settings = get_settings()
    endpoint = settings.minio_endpoint
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        config=BotoConfig(signature_version="s3v4"),
    )
