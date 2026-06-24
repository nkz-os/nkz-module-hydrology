"""NKZ Water Studio backend — FastAPI app factory.

CORS is handled by the api-gateway (the module has no direct public ingress).
Health probes are split: /healthz (liveness, always 200) and /readyz (readiness,
checks Redis). Both are exempt from auth and rate limiting.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import router as api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.enforce_required_secrets()  # fail-closed at startup
    logger.info(
        "%s v%s starting prefix=%s", settings.app_name, settings.app_version, settings.api_prefix
    )
    yield
    logger.info("%s shutting down", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="NKZ Water Studio backend API for the Nekazari platform",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        # Liveness — must never fail, exempt from rate limiter.
        return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        # Readiness — Redis reachable. Exempt from rate limiter.
        try:
            from redis import Redis
            Redis.from_url(settings.redis_url).ping()
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "not ready", "error": str(exc)})
        return {"status": "ready", "service": settings.app_name}

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
