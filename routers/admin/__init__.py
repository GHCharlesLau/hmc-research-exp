"""Admin package: compose sub-routers under the original URL paths."""

from fastapi import APIRouter

from routers.admin.auth import router as auth_router
from routers.admin.dashboard import router as dashboard_router
from routers.admin.participants import router as participants_router
from routers.admin.export import router as export_router
from routers.admin.test_tools import router as test_tools_router
from routers.admin.config import router as config_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(participants_router)
router.include_router(export_router)
router.include_router(config_router)
router.include_router(test_tools_router)
