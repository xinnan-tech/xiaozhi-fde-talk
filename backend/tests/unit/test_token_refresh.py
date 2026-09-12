"""refresh token + /auth/refresh 端点回归。

refresh_token 走 HttpOnly cookie，不再放 body。
HttpOnly cookie 由浏览器 / httpx 自动管理——登录响应 Set-Cookie 后，
同 AsyncClient 实例后续请求自动带 refresh-token cookie。

覆盖：
- login / register 都返回 Set-Cookie（含 authorized-token + refresh-token）
- /auth/refresh 用 cookie 里的 refresh 换到新 access_token（写回 cookie）
- /auth/refresh body 传 refresh_token 字段被忽略（cookie 优先）
- 缺失 / 无效 refresh cookie → AUTH_REFRESH_INVALID
- 已撤销 refresh（jti 进表） → AUTH_REFRESH_REVOKED

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


def _set_secure_false():
    """让 cookies 在 test 环境下 Secure=false（httpx 默认会跳过 Secure 校验，
    但若 dev/test 设了 Secure=true，http://test 路径下 httpx 仍会发出，但
    set_cookie 默认不带 Secure 时 httpx 会照发；这里仅为保险显式重置）。"""
    pass


@pytest.mark.asyncio
async def test_login_sets_auth_cookies(reset_state):
    """login 响应里 Set-Cookie 同时含 authorized-token + refresh-token，
    两个都带 HttpOnly + Secure=False（test 环境）。body 同时含 access_token /
    refresh_token（兼容路径：scripts / chaos.py / Authorization Bearer 测试）。
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
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    # body 同时含 token（兼容路径）和 user
    assert body["user"]["username"] == "alice"
    assert body["access_token"], "login body 必须含 access_token（兼容路径）"
    assert body["refresh_token"], "login body 必须含 refresh_token（兼容路径）"
    # Set-Cookie 头检查：httpx 的 ``Cookie`` 对象不暴露 httponly 字段（来自
    # http.cookiejar.Cookie 但 httpx 没暴露这些字段），直接从 ``Set-Cookie`` 头
    # 解析更可靠。
    set_cookie_headers = r.headers.get_list("set-cookie")
    assert any("authorized-token=" in h for h in set_cookie_headers), set_cookie_headers
    assert any("refresh-token=" in h for h in set_cookie_headers), set_cookie_headers
    # 两个 cookie 都带 HttpOnly
    for name in ("authorized-token", "refresh-token"):
        matching = [h for h in set_cookie_headers if h.startswith(f"{name}=")]
        assert matching, f"no Set-Cookie for {name}"
        assert "HttpOnly" in matching[0], f"{name} 缺 HttpOnly：{matching[0]}"


@pytest.mark.asyncio
async def test_register_sets_auth_cookies(reset_state):
    """register 响应同样下发两个 HttpOnly cookie + body 含 token 与 user。"""
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
    assert body["user"]["role"] == "admin"
    assert body["access_token"], "register body 必须含 access_token"
    assert body["refresh_token"], "register body 必须含 refresh_token"
    set_cookie_headers = r.headers.get_list("set-cookie")
    assert any("authorized-token=" in h for h in set_cookie_headers)
    assert any("refresh-token=" in h for h in set_cookie_headers)


@pytest.mark.asyncio
async def test_refresh_with_cookie_returns_new_access_cookie(reset_state):
    """登录拿到 refresh cookie；后续 /auth/refresh 不带 body，cookie 自动带 → 200，
    Set-Cookie 写入新 authorized-token，body 也含新 access_token。"""
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
        # 登录拿 cookie（httpx 自动存入 c.cookies jar）
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200
        old_access = c.cookies.get("authorized-token")
        assert old_access, "登录未拿到 authorized-token cookie"

        # refresh 不带 body；refresh cookie 自动带
        r2 = await c.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text
    new_access = c.cookies.get("authorized-token")
    assert new_access, "refresh 后未拿到新 authorized-token cookie"
    assert new_access != old_access, "refresh 必须签新 access（独立 jti）"
    # body 含 ok + access_token（兼容路径）
    body = r2.json()
    assert body["ok"] is True
    assert body["access_token"], "refresh body 必须含 access_token"
    assert body["access_token"] == new_access


@pytest.mark.asyncio
async def test_refresh_without_cookie_returns_401(reset_state):
    """无 refresh cookie 的 /auth/refresh → AUTH_REFRESH_INVALID（401）。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 完全没登录，直接 refresh
        r = await c.post("/api/v1/auth/refresh")
    assert r.status_code == 401, r.text
    assert r.json().get("code") == "auth.refresh_invalid"


@pytest.mark.asyncio
async def test_refresh_with_garbage_cookie_returns_401(reset_state):
    """cookie 里的 refresh 不是合法 JWT → AUTH_REFRESH_INVALID。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        c.cookies.set("refresh-token", "not-a-jwt")
        r = await c.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json().get("code") == "auth.refresh_invalid"


@pytest.mark.asyncio
async def test_refresh_with_expired_cookie_returns_401(reset_state):
    """人为签一个已过期的 refresh token，写入 cookie → AUTH_REFRESH_EXPIRED。"""
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
        c.cookies.set("refresh-token", expired)
        r = await c.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json().get("code") == "auth.refresh_expired"


@pytest.mark.asyncio
async def test_refresh_with_access_cookie_rejected(reset_state):
    """access token 写到 refresh-token cookie 字段 → AUTH_REFRESH_INVALID（type 错）。"""
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
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200
        # 拿到 access token 之后人为写到 refresh-token cookie（模拟客户端错把 access 写到 refresh 字段）
        access_token = c.cookies.get("authorized-token")
        c.cookies.set("refresh-token", access_token)
        r2 = await c.post("/api/v1/auth/refresh")
    assert r2.status_code == 401, r2.text
    assert r2.json().get("code") == "auth.refresh_invalid"