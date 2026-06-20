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

    # Keycloak / JWT Authentication
    keycloak_url: str = "https://auth.example.com/auth"  # Override via KEYCLOAK_URL
    keycloak_realm: str = "nekazari"
    jwt_audience: str = "account"
    jwt_issuer: str = ""  # Auto-derived from keycloak_url + realm if empty
    
    # Service-to-service authentication
    module_management_key: str = ""
    
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
    minio_region: str = "us-east-1"

    # Open-Meteo cache
    openmeteo_cache_ttl_days: int = 1

    # DEM processing
    dem_max_size_mb: int = 50

    # Worker
    worker_timeout: int = 600
    
    @property
    def jwt_issuer_url(self) -> str:
        """Get the JWT issuer URL."""
        if self.jwt_issuer:
            return self.jwt_issuer
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
    
    @property
    def jwks_url(self) -> str:
        """Get the JWKS URL for token verification."""
        return f"{self.jwt_issuer_url}/protocol/openid-connect/certs"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
