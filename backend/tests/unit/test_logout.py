"""/auth/logout 端点 + refresh token 撤销语义。"""
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
async def test_logout_revokes_refresh_token(reset_state):
    app = reset_state
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("Strong1!pwd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 1) 登录拿到 refresh_token
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "Strong1!pwd",
        })
        refresh_token = r.json()["refresh_token"]

        # 2) logout 撤销该 refresh
        r2 = await c.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}

        # 3) 再次 refresh 同一 token → AUTH_REFRESH_REVOKED
        r3 = await c.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r3.status_code == 401, r3.text
    assert r3.json().get("code") == "auth.refresh_revoked"


@pytest.mark.asyncio
async def test_logout_with_invalid_token_returns_200(reset_state):
    """任何入参都返 200（不区分用户/路径），避免凭 freshness 探查内部状态。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/logout", json={"refresh_token": "garbage"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_logout_with_already_revoked_token_returns_200(reset_state):
    """重复 logout 同一 token → 200，第二次什么都不做也不报错。"""
    app = reset_state
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async("Strong1!pwd")
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username="alice",
            password_hash=pwd_hash, role="user",
        ))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "Strong1!pwd",
        })
        refresh_token = r.json()["refresh_token"]

        r2 = await c.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
        r3 = await c.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert r2.status_code == 200
    assert r3.status_code == 200
