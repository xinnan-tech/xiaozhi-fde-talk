"""POST /api/v1/auth/register 端点 + service.register_user 事务锁。

覆盖：
- username 正则 4-32 位（字母/数字/_/-）
- service.register_user 首用户→admin
- 已有 admin + allow_registration=false → AUTH_REGISTRATION_DISABLED 403
- POST /auth/register 端点返 LoginResponse 含 user.role='admin'
"""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.config_store import get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.persistence.db import SessionLocal
from app.persistence.models import SystemConfig, User
from app.services.auth.service import register_user
from app.transport.http.schemas import RegisterRequest


# ─────────────────────────────────────────────────────────────────────
# lifespan 驱动：让 ConfigStore / DB 都初始化好
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")

    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _wipe() -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(
            text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
        )
        await s.commit()


@pytest.fixture
async def empty_db(_lifespan_app):
    """清 users + allow_registration 配置 → ConfigStore 缓存失效。"""
    from app.transport.http.routes.auth import _reset_for_test

    # 清空登录 / 注册限流桶：模块级 RateLimiter 跨用例持续累加，会污染后续测试。
    await _wipe()
    get_config_store().invalidate()
    _reset_for_test()
    yield _lifespan_app
    # teardown：再清一次，避免下一个测试看到本测试的副作用
    await _wipe()
    get_config_store().invalidate()
    _reset_for_test()


# ─────────────────────────────────────────────────────────────────────
# Step 1: username 正则
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("u", ["alice", "Bob_1", "usr-9", "abcd"])
def test_register_username_accepts_valid(u):
    RegisterRequest(username=u, password="Strong1!pwd", confirm_password="Strong1!pwd")


@pytest.mark.parametrize("u", ["ab", "a" * 33, "alice bob", "张三", ""])
def test_register_username_rejects_invalid(u):
    with pytest.raises(ValidationError):
        RegisterRequest(username=u, password="Strong1!pwd", confirm_password="Strong1!pwd")


# ─────────────────────────────────────────────────────────────────────
# Step 5: service.register_user 首用户→admin
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_first_user_becomes_admin(empty_db):
    async with SessionLocal() as db:
        async with db.begin():
            current = await register_user(db, "alice", "Strong1!pwd")
        assert current.role == "admin"
        assert current.username == "alice"
        assert current.user_id
        # 直接查 DB 行验证 password_changed_at 已写入（service 内部走 user_repo.create）
        row = (await db.execute(
            select(User).where(User.username == "alice")
        )).scalar_one()
        assert row.password_changed_at is not None


# ─────────────────────────────────────────────────────────────────────
# Step 9: 已有 admin + allow_registration=false → 拒
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_blocked_when_disallowed(empty_db):
    # 准备：插 1 个 admin，并显式 set allow_registration=false（同步内存缓存）
    async with SessionLocal() as s:
        async with s.begin():
            s.add(User(
                id=str(uuid.uuid4()), username="existing_admin",
                password_hash="x", role="admin",
            ))
        await get_config_store().set("auth.allow_registration", "false")
    async with SessionLocal() as db:
        with pytest.raises(I18nError) as ei:
            async with db.begin():
                await register_user(db, "bob", "Strong1!pwd")
        assert ei.value.code == Keys.AUTH_REGISTRATION_DISABLED.value
        assert ei.value.http_status == 403


# ─────────────────────────────────────────────────────────────────────
# Step 13: POST /auth/register 端点
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_endpoint_returns_login_response(empty_db):
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/register", json={
            "username": "alice",
            "password": "Strong1!pwd",
            "confirm_password": "Strong1!pwd",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["user"]["username"] == "alice"
    assert "access_token" in body
    assert body["access_token"]
    # Wave 3 P1 #23 refresh token：register 路径同步返回
    assert "refresh_token" in body
    assert body["refresh_token"]


@pytest.mark.asyncio
async def test_register_endpoint_password_mismatch_400(empty_db):
    """两次密码不一致 → AUTH_PASSWORD_MISMATCH 400。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/register", json={
            "username": "alice",
            "password": "Strong1!pwd",
            "confirm_password": "Different1!pwd",
        })
    assert r.status_code == 400, r.text
    body = r.json()
    # 错误体由 I18nError 异常处理器转译
    assert body.get("code") == Keys.AUTH_PASSWORD_MISMATCH.value


@pytest.mark.asyncio
async def test_register_endpoint_duplicate_username_409(empty_db):
    """首用户已注册（username='alice'），再注册同名 → AUTH_USERNAME_TAKEN 409。"""
    app = empty_db
    # 首用户注册后 allow_registration 默认 false，第二次注册会被 AUTH_REGISTRATION_DISABLED
    # 挡在 IntegrityError 之前；显式放开以验证 unique 路径。
    await get_config_store().set("auth.allow_registration", "true")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.post("/api/v1/auth/register", json={
            "username": "alice",
            "password": "Strong1!pwd",
            "confirm_password": "Strong1!pwd",
        })
        assert r1.status_code == 200, r1.text
        r2 = await c.post("/api/v1/auth/register", json={
            "username": "alice",
            "password": "Another1!pwd",
            "confirm_password": "Another1!pwd",
        })
    assert r2.status_code == 409, r2.text
    body = r2.json()
    assert body.get("code") == Keys.AUTH_USERNAME_TAKEN.value
