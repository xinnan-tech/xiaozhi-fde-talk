"""P2-7 · admin 改密码走独立端点。

M9: 旧实现 demo_password 在 ConfigStore + bootstrap.py 写死读；
admin UI 改了无效。改为 POST /admin/auth/password → 直接改 users.password_hash。

单元测试：手动驱动 lifespan 后用 ASGITransport 打 FastAPI app，不依赖运行中的后端服务。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.persistence.db import SessionLocal
from app.persistence.models import User


# ─────────────────────────────────────────────────────────────────────
# lifespan 驱动：让 JWT secret / ConfigStore / templates 都初始化好
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
    """整个模块共用一个 app + 已跑过 lifespan。

    前提：DB 已通过 alembic 升级到 head（含 0005_jwt_secret_seed），
    system.jwt_secret 已种入，lifespan 启动 JWTSecretResolver.resolve() 会直接
    从 DB 加载，不会触发 _save_to_db。
    """
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


async def _make_admin(username: str, password: str, role: str = "admin") -> str:
    async with SessionLocal() as session:
        existing = (await session.execute(
            select(User).where(User.username == username)
        )).scalars().first()
        if existing is None:
            uid = str(uuid.uuid4())
            session.add(User(
                id=uid, username=username,
                password_hash=hash_password(password), role=role,
            ))
            await session.commit()
            return uid
        existing.password_hash = hash_password(password)
        existing.role = role
        await session.commit()
        return existing.id


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post("/api/v1/auth/login",
                             json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
async def admin_client(_lifespan_app):
    username = f"pw_admin_{uuid.uuid4().hex[:8]}"
    password = "old_pw"
    await _make_admin(username, password)
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, username, password)
        yield client, token, username


# ─────────────────────────────────────────────────────────────────────
# tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_admin_password_changes_hash(admin_client):
    """POST /admin/auth/password → 改 users.password_hash；旧密码失效，新密码可用。"""
    client, token, username = admin_client
    new_password = "completely_new_pw_42"

    resp = await client.post(
        "/api/v1/admin/auth/password",
        json={"username": username, "new_password": new_password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    async with SessionLocal() as session:
        row = (await session.execute(
            select(User).where(User.username == username)
        )).scalars().one()
        assert verify_password(new_password, row.password_hash)
        assert not verify_password("old_pw", row.password_hash)


@pytest.mark.asyncio
async def test_post_admin_password_unauthenticated_401(_lifespan_app):
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/auth/password",
            json={"username": "x", "new_password": "y"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_admin_password_unknown_user_404(admin_client):
    client, token, _ = admin_client
    resp = await client.post(
        "/api/v1/admin/auth/password",
        json={"username": "nope_does_not_exist", "new_password": "valid_len_pw_42"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_pw", ["", "1234567", "x" * 73])
async def test_post_admin_password_validation_bad_pw_422(admin_client, bad_pw):
    """空 / 不足 8 位 / 超 72 位（bcrypt 上限）一律 422，不落到 hash 环节。"""
    client, token, username = admin_client
    resp = await client.post(
        "/api/v1/admin/auth/password",
        json={"username": username, "new_password": bad_pw},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_admin_password_non_admin_403(_lifespan_app):
    username = f"pw_user_{uuid.uuid4().hex[:8]}"
    await _make_admin(username, "secret123", role="user")

    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, username, "secret123")
        resp = await client.post(
            "/api/v1/admin/auth/password",
            json={"username": "any", "new_password": "newsecret123"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403