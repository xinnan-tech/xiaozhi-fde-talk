"""GET /auth/me 三态断言：未登录 / 凭据无效 / 已登录。

未登录态不应复用「用户名或密码错误」提示——前者语义是「请先登录」，
后者语义是「已登录尝试凭据失败」。两个语义用不同 i18n key 区分，
避免前端拦截器在首访无 cookie 时误弹「用户名或密码错误」toast。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.persistence.db import SessionLocal


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


async def _wipe() -> None:
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
    await _wipe()
    from app.core.config_store import get_config_store
    get_config_store().invalidate()
    yield _lifespan_app
    await _wipe()
    get_config_store().invalidate()


async def test_auth_me_no_cookie_returns_not_authenticated(empty_db):
    """无 cookie 首访：401 + code=http.auth.not_authenticated。

    校验点：detail.code 不能是 invalid_credentials——前者会触发前端
    「用户名或密码错误」toast，后者文案是「请先登录」。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/auth/me")
    body = r.json()
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
    assert body.get("code") == "http.auth.not_authenticated", body
    assert body.get("detail"), body


async def test_auth_me_invalid_cookie_returns_invalid_credentials(empty_db):
    """cookie 存在但 JWT 非法：401 + invalid_credentials（语义是凭据失败）。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/api/v1/auth/me",
            cookies={"authorized-token": "garbage.token.value"},
        )
    body = r.json()
    assert r.status_code == 401, r.text
    assert body.get("code") == "http.auth.invalid_credentials", body


async def test_auth_me_after_register_returns_user(empty_db):
    """注册拿 token 后 /auth/me 返 UserInfo——回归基线不被新逻辑破坏。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/register", json={
            "username": "first",
            "password": "Strong1!pwd",
            "confirm_password": "Strong1!pwd",
        })
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]

        r = await c.get(
            "/api/v1/auth/me",
            cookies={"authorized-token": token},
        )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "first"
    assert r.json()["role"] == "admin"
