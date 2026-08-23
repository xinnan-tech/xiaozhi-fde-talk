"""GET /auth/registration-status 公开端点。

零用户强制 allow_registration=true（首用户注册路径必须通畅）；
有用户时按 auth.allow_registration key 当前值返。响应体只暴露 allow_registration，
不暴露 user_count / has_admin（防侦察）。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.persistence.db import SessionLocal
from app.persistence.models import User


# ─────────────────────────────────────────────────────────────────────
# lifespan 驱动：让 ConfigStore / DB 都初始化好
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
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
# helpers
# ─────────────────────────────────────────────────────────────────────


async def _wipe() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(
            text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
        )
        await s.commit()


@pytest.fixture
async def empty_db(_lifespan_app):
    await _wipe()
    # 清 ConfigStore 内存缓存（DB 已清，避免缓存命中返旧值）
    from app.core.config_store import get_config_store

    get_config_store().invalidate()
    yield _lifespan_app


# ─────────────────────────────────────────────────────────────────────
# tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_zero_users_forces_true(empty_db):
    transport = ASGITransport(app=empty_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/auth/registration-status")
    assert r.status_code == 200, r.text
    assert r.json() == {"allow_registration": True}


@pytest.mark.asyncio
async def test_status_with_users_respects_key(empty_db):
    # 插 1 个用户：用户数 > 0，触发按 key 取值分支
    async with SessionLocal() as s:
        s.add(User(id="u-rs-1", username="alice_rs", password_hash="x", role="user"))
        await s.commit()
    # 用 ConfigStore.set（不走方言特定的 INSERT...ON CONFLICT，三方言通用）
    from app.core.config_store import get_config_store

    await get_config_store().set("auth.allow_registration", "false")

    transport = ASGITransport(app=empty_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/auth/registration-status")
    assert r.status_code == 200, r.text
    assert r.json() == {"allow_registration": False}
