"""
NKZ Water Studio Backend - Configuration

Environment-based configuration using pydantic-settings.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "NKZ Water Studio"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # API
    api_prefix: str = "/api/v1/hydrology"
    cors_origins: list[str] = []  # Set via CORS_ORIGINS env var; empty = deny all cross-origin

    # HMAC signature validation (shared secret with api-gateway + entity-manager).
    # The gateway signs X-Auth-Signature for every proxied request; the module
    # verifies it fail-closed to prevent X-Tenant-ID spoofing from inside the cluster.
    hmac_secret: str = ""
    require_hmac: bool = True
    
    # Service-to-service authentication
    module_management_key: str = ""
    internal_service_secret: str = ""

    # Self URL (used for subscription notification endpoints)
    self_url: str = "http://hydrology-api-service:8000"
    eu_elevation_url: str = "http://elevation-api-service:80"

    # NGSI-LD Context
    orion_ld_context: str = "http://api-gateway-service:5000/ngsi-ld-context.json"
    
    # NGSI-LD / Orion-LD
    orion_ld_url: str = "http://orion-ld-service:1026"
    context_url: str = "http://api-gateway-service:5000/ngsi-ld-context.json"

    # Database (optional - uncomment if using)
    # database_url: str = ""
    
    # Redis / RQ
    redis_url: str = "redis://localhost:6379/0"

    # MinIO / S3-compatible storage
    minio_endpoint: str = "http://minio-service:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "nkz-hydrology"
    minio_public_url: str = "https://minio.robotika.cloud"
    minio_region: str = "us-east-1"

    # Open-Meteo cache
    openmeteo_cache_ttl_days: int = 1

    # DEM processing
    dem_max_size_mb: int = 50

    # Worker
    worker_timeout: int = 600
    
    def enforce_required_secrets(self) -> None:
        """Fail fast at startup if security-critical secrets are missing."""
        if self.require_hmac and not self.hmac_secret:
            raise RuntimeError(
                "HMAC_SECRET is required when REQUIRE_HMAC=true "
                "(fail-closed). Set it from the shared jwt-secret/secret."
            )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
