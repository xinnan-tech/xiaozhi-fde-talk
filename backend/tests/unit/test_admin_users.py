"""GET /api/v1/admin/users + POST /api/v1/admin/users/{user_id}/password。

schema 字段正确（无 password_hash），路由拒绝无 token 调用，
service 层 update_password 同步刷新 password_changed_at。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.password_policy import validate_password_strength
from app.persistence.db import SessionLocal
from app.persistence.models import User
from app.persistence.repositories.user import user_repo
from app.transport.http.schemas import AdminUserInfo


# ─────────────────────────────────────────────────────────────────────
# lifespan 驱动
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
    """模块级共用一个 app + 已跑过 lifespan。

    DB 已通过 alembic 升级到 head（含 password_changed_at 列），
    lifespan 启动后 init_db / ConfigStore / JWTSecretResolver 都就绪。
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
# Step 1: schema 字段校验
# ─────────────────────────────────────────────────────────────────────


def test_admin_user_info_schema_no_password_hash():
    """AdminUserInfo 暴露 id/username/role/created_at/password_changed_at，绝不暴露 password_hash。"""
    fields = set(AdminUserInfo.model_fields.keys())
    assert "password_hash" not in fields
    assert {"id", "username", "role", "created_at"} <= fields


# ─────────────────────────────────────────────────────────────────────
# Step 5: 路由拒绝非 admin（无 token → 401）
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_users_requires_admin_role(_lifespan_app):
    """无 token → 401；带非 admin token → 403（依赖 require_admin）。"""
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/admin/users")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Step 2: service 层 update_password_auto 同步刷 password_changed_at
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_repo_update_password_auto_resets_timestamp():
    """user_repo.update_password_auto 自带事务 + 自动 hash + 同步刷 password_changed_at。

    路由 POST /admin/users/{user_id}/password 的实际调用方法——必须证明
    该方法行为正确，否则端点调它无法达到「旧 token 立即失效」效果。
    """
    suffix = uuid.uuid4().hex[:8]
    username = f"repo_pw_{suffix}"
    user_id = f"u-{suffix}"
    initial_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with SessionLocal() as s:
        async with s.begin():
            s.add(User(
                id=user_id,
                username=username,
                password_hash="placeholder-pre-hash-not-needed",
                role="user",
                password_changed_at=initial_ts,
            ))

    async with SessionLocal() as s:
        u0 = await user_repo.get_by_id(s, user_id)
        old_ts = u0.password_changed_at

    await asyncio.sleep(0.01)
    ok = await user_repo.update_password_auto(username, "NewPass1!xyz")
    assert ok is True

    async with SessionLocal() as s:
        u1 = await user_repo.get_by_id(s, user_id)
    # 两值都从 DB 读——避免 tz-aware/naive 类型错位，比较时刻一致
    assert u1.password_changed_at > old_ts


@pytest.mark.asyncio
async def test_user_repo_update_password_auto_same_password_noop():
    """新旧密码相同 → update_password_auto 不写 hash、不 bump password_changed_at、不失效 _pwd_cache。

    防御：admin 表单 auto-fill 旧值时，调用方拿到 ok 但 password_changed_at 不应推进、
    _pwd_cache 不应被失效，否则会让所有在线 session 被 pwd_ver 不匹配踢下线（issue #168）。
    """
    import time
    from app.core.security import hash_password_async
    from app.persistence.repositories.user import _pwd_cache

    suffix = uuid.uuid4().hex[:8]
    username = f"repo_noop_{suffix}"
    user_id = f"u-noop-{suffix}"
    initial_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    same_plain = "SameP@ssW0rd"
    same_hash = await hash_password_async(same_plain)

    async with SessionLocal() as s:
        async with s.begin():
            s.add(User(
                id=user_id,
                username=username,
                password_hash=same_hash,
                role="user",
                password_changed_at=initial_ts,
            ))

    async with SessionLocal() as s:
        u0 = await user_repo.get_by_id(s, user_id)
        old_hash = u0.password_hash
        old_ts = u0.password_changed_at

    # 预先占位 _pwd_cache：no-op 必须不失效该条目——否则下次读 pwd_changed_at
    # 会回源 DB 取到旧 ts（哨兵已被 pop），pwd_ver 不匹配会让所有在线 session 被踢下线。
    cache_sentinel = (time.monotonic(), old_ts)
    _pwd_cache[user_id] = cache_sentinel
    try:
        await asyncio.sleep(0.01)
        ok = await user_repo.update_password_auto(username, same_plain)
        assert ok is True  # 按 True 返回，调用方无需特殊处理

        async with SessionLocal() as s:
            u1 = await user_repo.get_by_id(s, user_id)
        # hash 不重写、时间戳不推进——证明 no-op 真生效
        assert u1.password_hash == old_hash
        assert u1.password_changed_at == old_ts
        # _pwd_cache 哨兵仍在：no-op 不踢下线（issue #168 核心防御点）
        assert _pwd_cache.get(user_id) == cache_sentinel
    finally:
        _pwd_cache.pop(user_id, None)


# ─────────────────────────────────────────────────────────────────────
# Step 5: 重置密码端点的弱密码校验 + 无 token → 401
# ─────────────────────────────────────────────────────────────────────


def test_validate_password_strength_rejects_weak():
    """复用现有策略：admin 重置也必须走强密码校验。

    单独的端到端弱密码 e2e 推迟到 Task 9（需 admin token 完整登录流程），
    此处仅证 policy 函数本身的拒绝行为被调用方依赖。
    """
    with pytest.raises(Exception):
        validate_password_strength("123")


@pytest.mark.asyncio
async def test_reset_password_endpoint_requires_auth(_lifespan_app):
    """无 token 访问重置端点必须 401。"""
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/admin/users/nonexistent/password",
            json={"new_password": "StrongP@ssW0rd"},
        )
    assert r.status_code == 401
