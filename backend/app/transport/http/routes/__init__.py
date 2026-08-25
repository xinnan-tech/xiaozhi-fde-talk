"""transport/http/routes 包：按资源拆分的路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.transport.http.routes.admin_config import router as admin_config_router
from app.transport.http.routes.admin_users import router as admin_users_router
from app.transport.http.routes.auth import router as auth_router
from app.transport.http.routes.diagnostics import router as diagnostics_router
from app.transport.http.routes.interviews import router as interviews_router
from app.transport.http.routes.reports import router as reports_router
from app.transport.http.routes.skills import router as skills_router
from app.transport.http.routes.templates import router as templates_router
from app.transport.http.routes.version import router as version_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(templates_router)
router.include_router(interviews_router)
router.include_router(reports_router)
router.include_router(skills_router)
router.include_router(admin_config_router)
router.include_router(admin_users_router)
router.include_router(diagnostics_router)
router.include_router(version_router)

__all__ = ["router"]
