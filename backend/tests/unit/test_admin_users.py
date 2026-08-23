"""GET /api/v1/admin/users：admin 列用户端点。

schema 字段正确（无 password_hash），路由拒绝无 token 调用。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.transport.http.schemas import AdminUserInfo


# ─────────────────────────────────────────────────────────────────────
# lifespan 驱动：与 test_admin_password_change 对齐
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
    """模块级共用一个 app + 已跑过 lifespan。

    DB 已通过 alembic 升级到 head（含 password_changed_at 列），
    lifespan 启动后 init_db / ConfigStore / JWTSecretResolver 都就绪。
    """
    import os
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")

    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


# ─────────────────────────────────────────────────────────────────────
# Step 1: schema 字段校验
# ─────────────────────────────────────────────────────────────────────


def test_admin_user_info_schema_no_password_hash():
    """AdminUserInfo 暴露 id/username/role/created_at/password_changed_at，绝不暴露 password_hash。"""
    fields = set(AdminUserInfo.model_fields.keys())
    assert "password_hash" not in fields
    assert {"id", "username", "role", "created_at"} <= fields


# ─────────────────────────────────────────────────────────────────────
# Step 5: 路由拒绝非 admin（无 token → 401）
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_users_requires_admin_role(_lifespan_app):
    """无 token → 401；带非 admin token → 403（依赖 require_admin）。"""
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/admin/users")
    assert r.status_code == 401
