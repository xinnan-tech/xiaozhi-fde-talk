"""E2E：用户相关 request schema 加固 extra="forbid" 回归覆盖。

背景：BaseModel 默认 extra="ignore" 会静默丢弃多余字段（如 user_id / role）。
当前实现里这些字段没有 path 被采纳，无即时越权；但 future field 进来后
形成静默越权窗口。本测试锁定：

- 4 个 schema（LoginRequest / RegisterRequest / ChangePasswordRequest /
  AdminResetPasswordRequest）拒绝多余字段 → 422
- 无多余字段的合法请求仍按既有 happy path 走 → 200（不破既有行为）

用例：

| 端点                            | 注入字段                | 期望 |
|--------------------------------|-----------------------|------|
| POST /auth/login               | user_id                | 422  |
| POST /auth/login               | role                   | 422  |
| POST /auth/register            | role                   | 422  |
| POST /auth/change-password     | user_id                | 422  |
| POST /admin/users/{id}/password | user_id               | 422  |
| POST /auth/login               | （无多余字段）            | 200  |
| POST /auth/register            | （无多余字段）            | 200  |

不依赖同事 conftest.py——`--noconftest` 跑（项目已有先例）。
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config_store import get_config_store


_STRONG_PWD = "Strong1!pwd"


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


@pytest.fixture
async def empty_db(_lifespan_app):
    """基于 app，启动后回到空 DB——与 test_change_password_authorization 同款。"""
    from sqlalchemy import text
    from app.persistence.db import SessionLocal

    async def _wipe() -> None:
        async with SessionLocal() as s:
            async with s.begin():
                await s.execute(text("DELETE FROM reports"))
                await s.execute(text("DELETE FROM interviews"))
                await s.execute(text("DELETE FROM users"))
                await s.execute(
                    text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
                )

    await _wipe()
    get_config_store().invalidate()
    yield _lifespan_app
    await _wipe()
    get_config_store().invalidate()


async def _register(c: AsyncClient, username: str, password: str = _STRONG_PWD) -> dict:
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


# ─────────────────────────────────────────────────────────────────────────────
# 注入字段应被 422 拒收（forbid 行为）
# ─────────────────────────────────────────────────────────────────────────────


async def test_login_rejects_extra_user_id_field(empty_db):
    """POST /auth/login 注入 user_id → 422，不该被忽略。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "x", "user_id": "x"},
        )
        assert r.status_code == 422, (
            f"LoginRequest 应 forbid user_id，实际 {r.status_code}：{r.text}"
        )


async def test_login_rejects_extra_role_field(empty_db):
    """POST /auth/login 注入 role → 422。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "x", "role": "admin"},
        )
        assert r.status_code == 422, (
            f"LoginRequest 应 forbid role，实际 {r.status_code}：{r.text}"
        )


async def test_register_rejects_extra_role_field(empty_db):
    """POST /auth/register 注入 role → 422（防越权申请成 admin）。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={
                "username": "validUser1",
                "password": "Strong1!pwd",
                "confirm_password": "Strong1!pwd",
                "role": "admin",
            },
        )
        assert r.status_code == 422, (
            f"RegisterRequest 应 forbid role，实际 {r.status_code}：{r.text}"
        )


async def test_change_password_rejects_extra_user_id_field(empty_db):
    """POST /auth/change-password 注入 user_id → 422。"""
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
                "new_password": "Strong1!new",
                "user_id": "x",
            },
        )
        assert r.status_code == 422, (
            f"ChangePasswordRequest 应 forbid user_id，实际 {r.status_code}：{r.text}"
        )


async def test_admin_reset_password_rejects_extra_user_id_field(empty_db):
    """POST /admin/users/{id}/password 注入 user_id → 422。

    目标用户在路径 {user_id} 里已经指定，body 再 user_id 即冗余攻击面。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin = await _register(c, "admin1")
        admin_token = admin["access_token"]
        target_id = admin["user"]["id"]

        r = await c.post(
            f"/api/v1/admin/users/{target_id}/password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "new_password": _STRONG_PWD,
                "user_id": "x",
            },
        )
        assert r.status_code == 422, (
            f"AdminResetPasswordRequest 应 forbid user_id，实际 {r.status_code}：{r.text}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path：合法无多余字段请求仍按既有行为返回 200
# ─────────────────────────────────────────────────────────────────────────────


async def test_login_without_extra_fields_still_returns_200(empty_db):
    """POST /auth/login 无多余字段（合法请求）→ 200。

    lockdown 不应破既有 happy path：admin 用户预注册、login 走通。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "first_admin")

        r = await c.post(
            "/api/v1/auth/login",
            json={"username": "first_admin", "password": _STRONG_PWD},
        )
        assert r.status_code == 200, (
            f"合法 login 应 200，实际 {r.status_code}：{r.text}"
        )


async def test_register_without_extra_fields_still_returns_200(empty_db):
    """POST /auth/register 无多余字段（合法请求）→ 200。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "first_admin")
        await get_config_store().set("auth.allow_registration", "true")

        r = await c.post(
            "/api/v1/auth/register",
            json={
                "username": "validUser1",
                "password": _STRONG_PWD,
                "confirm_password": _STRONG_PWD,
            },
        )
        assert r.status_code == 200, (
            f"合法 register 应 200，实际 {r.status_code}：{r.text}"
        )
