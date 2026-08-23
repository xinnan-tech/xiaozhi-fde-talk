"""E2E：普通用户自助改密（POST /auth/change-password）。

覆盖 5 个核心场景：
1. 普通 user 改自己密码（旧密码对）→ 200，旧 token 立即 401（pwd_ver 吊销）
2. 普通 user 改自己密码（旧密码错）→ 401
3. admin 改自己密码 → 200（admin 也能走自助改密端点）
4. 无 token 调改密 → 401
5. 新密码命中弱密码表 → 400

不调运行中的 8000 后端——用 ASGITransport 在进程内跑完整 app + lifespan，
与 test_authorization_boundary / test_auth_registration 同款。
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config_store import get_config_store
from app.persistence.db import SessionLocal


_STRONG_PWD = "Strong1!pwd"
_STRONG_PWD_NEW = "Strong1!new"


@pytest.fixture(scope="module")
async def _lifespan_app():
    """模块级共用一个 app + 已跑过 lifespan。"""
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")

    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _wipe_db() -> None:
    async with SessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM reports"))
            await s.execute(text("DELETE FROM interviews"))
            await s.execute(text("DELETE FROM users"))
            await s.execute(
                text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
            )


@pytest.fixture
async def empty_db(_lifespan_app):
    await _wipe_db()
    get_config_store().invalidate()
    yield _lifespan_app
    await _wipe_db()
    get_config_store().invalidate()


async def _register(c: AsyncClient, username: str, password: str = _STRONG_PWD) -> dict:
    """注册用户，返回 {access_token, user}。"""
    r = await c.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
        },
    )
    assert r.status_code == 200, f"register {username} failed: {r.text}"
    return r.json()


async def test_user_can_change_own_password_and_old_token_revoked(empty_db):
    """普通 user 自助改密 → 200；改密后旧 token（pwd_ver 不匹配）调任何受保护端点 → 401。

    改密的核心安全语义：旧 token 立即吊销（不再给到 60s 缓存窗口期）。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 首用户（admin）放开注册，注册普通用户
        await _register(c, "first_admin")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        # bob 自助改密（旧密码对）→ 200
        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, f"bob 自助改密应 200，实际 {r.status_code}：{r.text}"
        assert r.json() == {"ok": True}

        # bob 旧 token 调受保护端点 → 401（pwd_ver 吊销）
        r = await c.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 401, (
            f"bob 改密后旧 token 应被 pwd_ver 吊销→401，"
            f"实际 {r.status_code}：{r.text}"
        )

        # bob 用新密码登录 → 200（确认新密码生效）
        r = await c.post(
            "/api/v1/auth/login",
            json={"username": "bobby", "password": _STRONG_PWD_NEW},
        )
        assert r.status_code == 200, (
            f"bob 用新密码登录应 200，实际 {r.status_code}：{r.text}"
        )


async def test_user_change_password_wrong_old_password_returns_401(empty_db):
    """普通 user 改密但旧密码错 → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "first_admin")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": "WrongOld1!pwd",
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"旧密码错误应 401，实际 {r.status_code}：{r.text}"
        )


async def test_admin_can_change_own_password_via_self_service(empty_db):
    """admin 也能走自助改密端点（不限 role=user）→ 200。

    防回归：admin 不应被自助端点特殊拒绝——admin 也是普通用户，admin token
    在自己账号上的写权限应放行。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin = await _register(c, "admin1")
        admin_token = admin["access_token"]

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, (
            f"admin 自助改密应 200，实际 {r.status_code}：{r.text}"
        )


async def test_anonymous_cannot_change_password(empty_db):
    """无 token 调改密端点 → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"无 token 应被 401 拦在改密端点外，实际 {r.status_code}：{r.text}"
        )


async def test_change_password_with_weak_new_password_returns_400(empty_db):
    """新密码命中弱密码表 → 400（validate_password_strength 兜底）。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "first_admin")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": "password",  # 命中 _WEAK_PASSWORDS
            },
        )
        assert r.status_code == 400, (
            f"弱密码应 400，实际 {r.status_code}：{r.text}"
        )
