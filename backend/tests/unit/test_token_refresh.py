"""refresh token + /auth/refresh 端点回归。

覆盖：
- login / register 都返回 refresh_token 字段
- /auth/refresh 用合法 refresh 换到新 access token
- /auth/refresh 用 access token 投到 refresh → AUTH_REFRESH_INVALID
  （type 字段不对）
- /auth/refresh 用过期 refresh → AUTH_REFRESH_EXPIRED
- /auth/refresh 用已撤销 refresh → AUTH_REFRESH_REVOKED

lifespan 绕过：测试装一个手搭 FastAPI 子集（同一路由 + 同一 Settings + DB SessionLocal），
不去启动 app.py 的 lifespan，避免 sessions.manager 的 _stop_flag asyncio.Event
（模块级单例）跨 pytest-asyncio 函数级 loop 互踩——Event 绑定首次 loop 后，
后续 loop 的 teardown 一调 stop_idle_watchdog 就 "bound to a different event loop"。
"""
from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.config_store import get_config_store
from app.persistence.bootstrap import init_db
from app.persistence.db import SessionLocal, engine
from app.persistence.models import User
from app.services.auth import token as tok
from app.core.settings import get_settings
from app.core.i18n.context import current_locale
from app.core.i18n.errors import I18nError


@asynccontextmanager
async def _stub_lifespan(_app):
    """只跑 init_db + config_store.warm；不挂 manager.idle_watchdog。"""
    await init_db()
    await get_config_store().warm()
    # 让 settings.jwt_secret 从 DB 注入（lifespan 原职责）
    from app.core.secret import JWTSecretResolver
    resolver = JWTSecretResolver(get_settings(), SessionLocal)
    get_settings().jwt_secret = await resolver.resolve()
    yield
    await engine.dispose()


def _wire_exception_handler(app: FastAPI) -> None:
    """create_app 里的 I18nError 异常处理器——把 code/localized 织成 JSON 响应。

    stub 模式下我们没走 create_app，但 HTTP 测试预期响应体形如
    {"detail": ..., "code": "auth.xxx"}；不挂这个 handler 测试会看到 I18nError
    的 ``__str__`` 而不是结构化 JSON。
    """
    @app.exception_handler(I18nError)
    async def _i18n_handler(request, exc: I18nError):  # noqa: ARG001
        locale = current_locale()
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.localized(locale=locale), "code": exc.code},
            headers={"Content-Language": locale},
        )


@pytest.fixture
async def _app():
    """函数级 fixture：每个用例一个独立 FastAPI + 独立 event loop，
    避免 module 单例（manager._stop_flag、asyncio.Lock）跨 loop 状态泄漏。"""
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()

    app = FastAPI(title="stub")
    app.router.lifespan_context = _stub_lifespan
    # 装 HTTP 路由（含 auth 等），但 manager 等 lifespan 路径不挂
    from app.transport.http.routes import router as api_router
    app.include_router(api_router)
    _wire_exception_handler(app)
    async with _stub_lifespan(app):
        yield app


@pytest.fixture
async def reset_state(_app):
    """每个用例清 users + allow_registration + rate limiter + revoked set。"""
    from sqlalchemy import text
    from app.transport.http.routes.auth import _reset_for_test
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(text("DELETE FROM system_config WHERE key = 'auth.allow_registration'"))
        await s.commit()
    get_config_store().invalidate()
    _reset_for_test()
    yield _app
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(text("DELETE FROM system_config WHERE key = 'auth.allow_registration'"))
        await s.commit()
    get_config_store().invalidate()
    _reset_for_test()


@pytest.mark.asyncio
async def test_login_returns_refresh_token(reset_state):
    app = reset_state
    # 种一个用户：直接写 DB 走 bcrypt 哈希
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"], "login 必须返回 refresh_token"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_register_returns_refresh_token(reset_state):
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/register", json={
            "username": "alice",
            "password": "StrongP@ssW0rd",
            "confirm_password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"], "register 必须返回 refresh_token"
    assert body["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_refresh_with_valid_refresh_token(reset_state):
    app = reset_state
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        login_body = r.json()
        refresh_token = login_body["refresh_token"]
        old_access = login_body["access_token"]

        r2 = await c.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["access_token"]
    assert body["access_token"] != old_access, "refresh 必须签新 access（独立 jti）"


@pytest.mark.asyncio
async def test_refresh_with_access_token_rejected(reset_state):
    """access token 投到 refresh 字段 → 必须 AUTH_REFRESH_INVALID（type 不对）。"""
    app = reset_state
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        access_token = r.json()["access_token"]
        r2 = await c.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert r2.status_code == 401, r2.text
    assert r2.json().get("code") == "auth.refresh_invalid"


@pytest.mark.asyncio
async def test_refresh_with_garbage_token_rejected(reset_state):
    """乱码 token → AUTH_REFRESH_INVALID。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert r.status_code == 401
    assert r.json().get("code") == "auth.refresh_invalid"


@pytest.mark.asyncio
async def test_refresh_with_expired_token_rejected(reset_state):
    """人为签一个已过期的 refresh token → AUTH_REFRESH_EXPIRED。"""
    app = reset_state
    settings_mod = tok.get_settings()
    secret = settings_mod.jwt_secret
    expired = pyjwt.encode(
        {
            "sub": "u-fake", "type": "refresh",
            "iat": time.time() - 7200, "exp": time.time() - 3600,
            "jti": "expired-jti", "iss": "xiaozhi-fde-talk",
            "aud": "xiaozhi-client", "pwd_ver": 1,
        },
        secret, algorithm="HS256",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/refresh", json={"refresh_token": expired})
    assert r.status_code == 401
    assert r.json().get("code") == "auth.refresh_expired"
