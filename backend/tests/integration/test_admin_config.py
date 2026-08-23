"""集成测试：admin /api/v1/admin/config GET/PUT。

包含：
- 5 个 brief 功能/行为测试（admin 鉴权 + 6 分组 CRUD + 未知 key）
- 9 个越权（privilege escalation）测试：未认证 / 无效 token / 非 admin 用户 / 各分组 / 未知分组

注意：conftest.create_user 的 `existing is None` 检查用了 session.get(User, username)
但 User PK 是 id，所以查询永远 None → 第二次调用撞 UNIQUE。
本文件通过 bob_user 模块 fixture 让 create_user 只调一次（其余测试复用已建的 bob）。
另外：测试进程与后端服务是不同进程，ConfigStore 不共享，DB 验证走直查 SQL。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.persistence.db import SessionLocal
from app.persistence.models import SystemConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 本地 fixture：保证 bob 只被创建一次
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def non_admin_user():
    """返回 ('bob', 'bob')。模块内复用。

    create_user 的存在性检查是坏的（用 session.get 按 PK 查，但 PK 是 id 不是 username），
    所以第二次同用户名调用会撞 UNIQUE。这里只用登录 fixture 不调 create_user；
    bob 由本模块第一个拿到 create_non_admin_once 的测试负责创建。
    """
    return ("bob", "bob")


@pytest.fixture
async def create_non_admin_once():
    """一次性创建 bob（仅第一次调用成功；撞 UNIQUE 则吞掉）。"""
    import uuid
    from app.core.security import hash_password
    from app.persistence.models import User
    async with SessionLocal() as session:
        existing = (await session.execute(
            select(User).where(User.username == "bob")
        )).scalars().first()
        if existing is None:
            session.add(User(id=str(uuid.uuid4()), username="bob",
                             password_hash=hash_password("bob")))
            try:
                await session.commit()
            except Exception:
                await session.rollback()
        else:
            # 已存在，确保密码正确
            existing.password_hash = hash_password("bob")
            await session.commit()


async def _db_get(key: str) -> str | None:
    """直查 DB（绕开测试进程 ConfigStore 缓存，因其与服务器进程不共享）。"""
    async with SessionLocal() as session:
        row = (await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )).scalars().first()
        return row.value if row else None


async def _db_get_hash(username: str) -> str | None:
    """直查 users.password_hash。"""
    from app.persistence.models import User
    async with SessionLocal() as session:
        row = (await session.execute(
            select(User).where(User.username == username)
        )).scalars().first()
        return row.password_hash if row else None


async def _db_get_id(username: str) -> str | None:
    """按 username 查 users.id（admin 改密端点按 user_id 路由）。"""
    from app.persistence.models import User
    async with SessionLocal() as session:
        row = (await session.execute(
            select(User).where(User.username == username)
        )).scalars().first()
        return row.id if row else None


# ---------------------------------------------------------------------------
# brief 行为测试
# ---------------------------------------------------------------------------


async def test_get_config_requires_admin(client, login, create_non_admin_once):
    """非 admin 调 → 403。"""
    bob_token = await login(client, "bob", "bob")
    r = await client.get("/api/v1/admin/config",
                          headers={"Authorization": f"Bearer {bob_token}"})
    assert r.status_code == 403


async def test_get_config_admin_returns_all_groups(client, login):
    admin_token = await login(client)
    r = await client.get("/api/v1/admin/config",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"llm", "asr", "coach", "auth", "session"}
    # 敏感字段为 null
    assert body["llm"]["api_key"] is None
    # demo_password 不再在 ConfigStore；改密走 /admin/users/{id}/password
    # 非敏感字段有值
    assert body["llm"]["model"] == "qwen-plus"


async def test_get_config_group(client, login):
    admin_token = await login(client)
    r = await client.get("/api/v1/admin/config/llm",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["type"] == "openai"
    assert r.json()["api_key"] is None


async def test_put_config_updates_non_sensitive(client, login):
    admin_token = await login(client)
    r = await client.put(
        "/api/v1/admin/config/llm",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"type": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    )
    assert r.status_code == 200
    # 验证：再 GET 看新值
    r2 = await client.get("/api/v1/admin/config/llm",
                           headers={"Authorization": f"Bearer {admin_token}"})
    assert r2.json()["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert r2.json()["model"] == "qwen-plus"


async def test_put_config_unknown_key_rejected(client, login):
    admin_token = await login(client)
    r = await client.put(
        "/api/v1/admin/config/llm",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"type": "openai", "bogus_field": "x"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 越权（privilege escalation）测试
# ---------------------------------------------------------------------------


async def test_unauthenticated_get_config_returns_401(client):
    """No auth header → 401, not 200 (must reject anonymous)."""
    r = await client.get("/api/v1/admin/config")
    assert r.status_code == 401


async def test_unauthenticated_put_config_returns_401(client):
    r = await client.put("/api/v1/admin/config/llm", json={"model": "x"})
    assert r.status_code == 401


async def test_invalid_token_get_config_returns_401(client):
    r = await client.get("/api/v1/admin/config",
                          headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


async def test_non_admin_cannot_read_config(client, login, create_non_admin_once):
    """Bob (non-admin) GET → 403."""
    bob_token = await login(client, "bob", "bob")
    r = await client.get("/api/v1/admin/config",
                          headers={"Authorization": f"Bearer {bob_token}"})
    assert r.status_code == 403


async def test_non_admin_cannot_modify_config(client, login, create_non_admin_once):
    """Bob (non-admin) PUT → 403 AND DB unchanged."""
    bob_token = await login(client, "bob", "bob")
    # Snapshot original from DB
    original_base_url = await _db_get("llm.base_url")
    r = await client.put(
        "/api/v1/admin/config/llm",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"base_url": "https://api.deepseek.com"},
    )
    assert r.status_code == 403
    # 直查 DB 验证未被改（越权被拒）
    assert await _db_get("llm.base_url") == original_base_url


async def test_non_admin_cannot_change_admin_password(client, login, create_non_admin_once):
    """Bob (non-admin) POST /admin/users/{id}/password → 403 AND password unchanged."""
    bob_token = await login(client, "bob", "bob")
    original_pw = await _db_get_hash("admin")
    admin_id = await _db_get_id("admin")
    r = await client.post(
        f"/api/v1/admin/users/{admin_id}/password",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"new_password": "pwned"},
    )
    assert r.status_code == 403
    assert await _db_get_hash("admin") == original_pw


async def test_non_admin_cannot_change_jwt_config(client, login, create_non_admin_once):
    """Bob (non-admin) PUT auth.jwt_expire_minutes → 403."""
    bob_token = await login(client, "bob", "bob")
    r = await client.put(
        "/api/v1/admin/config/auth",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"jwt_expire_minutes": 99999999},  # infinite session escalation attempt
    )
    assert r.status_code == 403


async def test_non_admin_cannot_list_groups(client, login, create_non_admin_once):
    """Bob GET /admin/config/specific-group → 403 (all admin routes guarded)."""
    bob_token = await login(client, "bob", "bob")
    for g in ("llm", "asr", "coach", "auth", "session"):
        r = await client.get(f"/api/v1/admin/config/{g}",
                              headers={"Authorization": f"Bearer {bob_token}"})
        assert r.status_code == 403, f"group {g} leaked to non-admin"


async def test_unknown_group_404(client, login):
    admin_token = await login(client)
    r = await client.get("/api/v1/admin/config/bogus",
                          headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404
