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


def get_presign_client():
    """boto3 S3 client for generating presigned URLs against the PUBLIC endpoint.

    Presigned URLs embed the host in the signature, so a URL signed against the
    internal endpoint (``minio-service:9000``) would fail at ``minio.robotika.cloud``.
    Sign against ``minio_public_url`` so browsers can fetch tenant PMTiles directly.
    Same creds/region/s3v4 as ``get_s3_client``.
    """
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_public_url,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        config=BotoConfig(signature_version="s3v4"),
    )
