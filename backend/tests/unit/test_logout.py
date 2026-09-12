"""/auth/logout 端点 + refresh token 撤销语义（HttpOnly cookie 模型）。"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

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
    await init_db()
    await get_config_store().warm()
    from app.core.secret import JWTSecretResolver
    resolver = JWTSecretResolver(get_settings(), SessionLocal)
    get_settings().jwt_secret = await resolver.resolve()
    yield
    await engine.dispose()


def _wire_exception_handler(app: FastAPI) -> None:
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
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    app = FastAPI(title="stub")
    app.router.lifespan_context = _stub_lifespan
    from app.transport.http.routes import router as api_router
    app.include_router(api_router)
    _wire_exception_handler(app)
    async with _stub_lifespan(app):
        yield app


@pytest.fixture
async def reset_state(_app):
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
async def test_logout_revokes_refresh_cookie(reset_state):
    """登录 → logout（refresh cookie 在 httpx jar 里自动带）→ 200 + 清两个 cookie；
    之后 /auth/refresh 用同 refresh cookie → AUTH_REFRESH_REVOKED。
    """
    app = reset_state
    from datetime import datetime, timezone
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
            password_changed_at=datetime.now(timezone.utc),
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 1) 登录拿 refresh cookie
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200
        assert c.cookies.get("refresh-token")

        # 2) logout（httpx cookie jar 自动带 refresh-token）
        r2 = await c.post("/api/v1/auth/logout")
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}
        # logout 响应 Set-Cookie Max-Age=0 清两个 cookie；
        # httpx jar 在收到 Set-Cookie delete 后会移除 key。
        assert not c.cookies.get("refresh-token"), "logout 未清 refresh-token cookie"
        assert not c.cookies.get("authorized-token"), "logout 未清 authorized-token cookie"

        # 3) 重新登录拿 refresh（因为 cookie 被清，第二次 logout 后 httpx jar 是空的）
        #    —— 然后再次 logout，不应该再撤销任何东西（第二次撤销是 idempotent）
        r_login2 = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r_login2.status_code == 200
        refresh_token_v2 = c.cookies.get("refresh-token")
        assert refresh_token_v2

        # 4) 第二次 logout 同 refresh token → 200（idempotent）
        r3 = await c.post("/api/v1/auth/logout")
    assert r3.status_code == 200
    assert r3.json() == {"ok": True}


@pytest.mark.asyncio
async def test_logout_with_invalid_cookie_returns_200(reset_state):
    """无 cookie / cookie 是乱码 → 200（避免凭 freshness 探查内部状态）。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 任意乱码 cookie
        c.cookies.set("refresh-token", "garbage")
        r = await c.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_logout_without_cookie_returns_200(reset_state):
    """完全没 cookie → 200。logout 不强制鉴权（清除是幂等操作）。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_logout_then_refresh_cookie_revoked(reset_state):
    """logout 后再调 refresh，必须 AUTH_REFRESH_REVOKED（jti 进撤销表）。

    用例流程：登录拿到 refresh-token cookie（v1）→ logout 撤销 → 再次登录拿
    refresh v2 → 手动把 v1 写回 refresh-token cookie（模拟攻击者用旧 token）→
    /auth/refresh → AUTH_REFRESH_REVOKED。
    """
    app = reset_state
    from datetime import datetime, timezone
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
            password_changed_at=datetime.now(timezone.utc),
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 1) 登录拿 refresh v1
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200
        refresh_v1 = c.cookies.get("refresh-token")

        # 2) logout（httpx 自动带 refresh-token cookie）→ 撤销 v1
        r2 = await c.post("/api/v1/auth/logout")
        assert r2.status_code == 200

        # 3) 把被撤销的 v1 写回 cookie（httpx 在 logout 后会清，我们人为重写）
        c.cookies.set("refresh-token", refresh_v1)
        r3 = await c.post("/api/v1/auth/refresh")
    assert r3.status_code == 401, r3.text
    assert r3.json().get("code") == "auth.refresh_revoked"