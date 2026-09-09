"""/auth/* 端点的 Set-Cookie 属性回归（HttpOnly cookie 安全契约）：

- authorized-token 必须 HttpOnly + SameSite=Lax
- refresh-token 必须 HttpOnly + SameSite=Strict
- 两条 cookie 都必须 Path=/（否则会被浏览器限定到某子路径，refresh / logout
  路径可能拿不到 → 假「已清」但实际仍在）
- logout 必须 Max-Age=0 清两条

这些是 #212 修复的「核心防线」。任何未来重构如果改坏了 Set-Cookie 头属性，
本测试会立刻报警——攻击者拿到 XSS 执行权后能否偷到 token，靠的就是浏览器
``document.cookie`` 看不到 HttpOnly 这条防线。
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.config_store import get_config_store
from app.core.i18n.context import current_locale
from app.core.i18n.errors import I18nError
from app.core.secret import JWTSecretResolver
from app.core.settings import get_settings
from app.persistence.bootstrap import init_db
from app.persistence.db import SessionLocal, engine
from app.persistence.models import User


def _cookie_attrs(raw_set_cookie: str) -> dict[str, bool]:
    """解析 Set-Cookie 头里的属性标记。SameSite 值大小写不敏感。"""
    lower = raw_set_cookie.lower()
    return {
        "name": raw_set_cookie.split("=", 1)[0].strip(),
        "httponly": "httponly" in lower,
        "samesite_lax": "samesite=lax" in lower,
        "samesite_strict": "samesite=strict" in lower,
        "path_root": "path=/" in lower,
        "secure": "secure;" in lower.replace(" ", ";")
        or lower.rstrip().endswith("; secure"),
    }


@asynccontextmanager
async def _stub_lifespan(_app):
    await init_db()
    await get_config_store().warm()
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


async def _seed_user(username: str, password: str) -> None:
    from datetime import datetime, timezone
    from app.core.security import hash_password_async
    pwd_hash = await hash_password_async(password)
    async with SessionLocal() as s:
        s.add(User(
            id=str(uuid.uuid4()), username=username,
            password_hash=pwd_hash, role="user",
            password_changed_at=datetime.now(timezone.utc),
        ))
        await s.commit()


def _find_cookie(raw_cookies: list[str], name: str) -> str | None:
    for line in raw_cookies:
        if line.split("=", 1)[0].strip() == name:
            return line
    return None


@pytest.mark.asyncio
async def test_login_sets_httponly_samesite_attrs(reset_state):
    """登录响应 Set-Cookie：两条 cookie 都 HttpOnly，access=Lax、refresh=Strict。"""
    app = reset_state
    await _seed_user("alice", "StrongP@ssW0rd")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200

    raw_cookies = r.headers.get_list("set-cookie")
    access = _find_cookie(raw_cookies, "authorized-token")
    refresh = _find_cookie(raw_cookies, "refresh-token")

    assert access, f"login 响应缺 authorized-token Set-Cookie: {raw_cookies}"
    assert refresh, f"login 响应缺 refresh-token Set-Cookie: {raw_cookies}"

    a = _cookie_attrs(access)
    r_ = _cookie_attrs(refresh)

    assert a["httponly"], f"authorized-token 必须 HttpOnly: {access}"
    assert a["samesite_lax"], f"authorized-token 必须 SameSite=Lax: {access}"
    assert a["path_root"], f"authorized-token 必须 Path=/: {access}"

    assert r_["httponly"], f"refresh-token 必须 HttpOnly: {refresh}"
    assert r_["samesite_strict"], f"refresh-token 必须 SameSite=Strict: {refresh}"
    assert r_["path_root"], f"refresh-token 必须 Path=/: {refresh}"


@pytest.mark.asyncio
async def test_register_sets_httponly_samesite_attrs(reset_state):
    """注册（首用户 = admin）响应同样写 HttpOnly cookie。"""
    app = reset_state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/register", json={
            "username": "newuser_" + uuid.uuid4().hex[:6],
            "password": "StrongP@ssW0rd",
            "confirm_password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200, r.text

    raw_cookies = r.headers.get_list("set-cookie")
    access = _find_cookie(raw_cookies, "authorized-token")
    refresh = _find_cookie(raw_cookies, "refresh-token")
    assert access and refresh
    assert _cookie_attrs(access)["httponly"]
    assert _cookie_attrs(refresh)["httponly"]


@pytest.mark.asyncio
async def test_refresh_writes_httponly_access_cookie(reset_state):
    """/auth/refresh 重写 access cookie——同样必须 HttpOnly + SameSite=Lax。"""
    app = reset_state
    await _seed_user("alice", "StrongP@ssW0rd")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200

        # 用 cookie jar（httpx 自动带 refresh）调 refresh
        r2 = await c.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text

    raw_cookies = r2.headers.get_list("set-cookie")
    access = _find_cookie(raw_cookies, "authorized-token")
    assert access, f"/auth/refresh 应重写 authorized-token: {raw_cookies}"
    a = _cookie_attrs(access)
    assert a["httponly"], f"refresh 写入的 access 必须 HttpOnly: {access}"
    assert a["samesite_lax"], f"refresh 写入的 access 必须 SameSite=Lax: {access}"


@pytest.mark.asyncio
async def test_logout_clears_both_cookies_with_path_root(reset_state):
    """/auth/logout 必须清两条 cookie，且 Path=/（与写入路径一致）。"""
    app = reset_state
    await _seed_user("alice", "StrongP@ssW0rd")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200

        r2 = await c.post("/api/v1/auth/logout")
    assert r2.status_code == 200

    raw_cookies = r2.headers.get_list("set-cookie")
    access_del = _find_cookie(raw_cookies, "authorized-token")
    refresh_del = _find_cookie(raw_cookies, "refresh-token")
    assert access_del, f"logout 响应缺 authorized-token 删除头: {raw_cookies}"
    assert refresh_del, f"logout 响应缺 refresh-token 删除头: {raw_cookies}"

    # Max-Age=0 是浏览器删除的判据
    for line, name in [(access_del, "authorized-token"), (refresh_del, "refresh-token")]:
        assert "max-age=0" in line.lower(), \
            f"{name} 删除必须 Max-Age=0: {line}"
        assert _cookie_attrs(line)["path_root"], \
            f"{name} 删除必须 Path=/（与写入路径一致才能真正清掉）: {line}"


@pytest.mark.asyncio
async def test_login_response_body_does_not_force_token_use(reset_state):
    """LoginResponse 兼容地仍带 token 字段，但前端主路径不读。
    本测试锁定 body schema 不变——scripts / chaos.py 还要用。"""
    app = reset_state
    await _seed_user("alice", "StrongP@ssW0rd")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
    assert r.status_code == 200
    body = r.json()
    assert "user" in body
    assert body["user"]["username"] == "alice"
    # 兼容路径字段存在（scripts 还要读），前端 main 路径不读
    assert "access_token" in body
    assert "refresh_token" in body