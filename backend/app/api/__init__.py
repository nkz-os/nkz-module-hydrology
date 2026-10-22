"""
NKZ Water Studio Backend - API Routes

Module-specific routers for hydrology analysis, background jobs,
and parcel setup lifecycle.
"""

from fastapi import APIRouter

from app.api.analyze import router as analyze_router
from app.api.jobs import router as jobs_router
from app.api.setup import router as setup_router
from app.api.visualization import router as visualization_router
from app.api.designs import router as designs_router
from app.api.zones import router as zones_router
from app.api.scenarios import router as scenarios_router
from app.api.alerts import router as alerts_router
from app.api.webhooks import router as webhooks_router


# =============================================================================
# Router Setup
# =============================================================================

router = APIRouter(tags=["NKZ Water Studio"])

# Include hydrology sub-routers
router.include_router(analyze_router)
router.include_router(jobs_router)
router.include_router(setup_router)
router.include_router(visualization_router)
router.include_router(designs_router)
router.include_router(zones_router)
router.include_router(scenarios_router)
router.include_router(alerts_router)
router.include_router(webhooks_router)
