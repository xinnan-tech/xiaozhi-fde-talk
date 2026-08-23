"""username 大小写归一：边界 .lower()，跨方言一致。"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config_store import get_config_store
from app.persistence.db import SessionLocal
from app.services.auth.service import authenticate_user, register_user


@pytest.fixture(autouse=True)
async def _wipe_users():
    """每测试清 users 表 + 重置 allow_registration 缓存——避免前一个测试残留污染。

    测试顺序敏感（注册后 count>0 走 allow_registration 分支），必须先清。
    """
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(
            text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
        )
        await s.commit()
    get_config_store().invalidate()
    yield


@pytest.mark.asyncio
async def test_register_normalizes_to_lowercase():
    async with SessionLocal() as db:
        async with db.begin():
            u = await register_user(db, "ALICE", "StrongP@ssW0rd")
    assert u.username == "alice"


@pytest.mark.asyncio
async def test_authenticate_case_insensitive_lookup():
    async with SessionLocal() as db:
        async with db.begin():
            await register_user(db, "alice", "StrongP@ssW0rd")
    async with SessionLocal() as db:
        # 登录时输大写也应该成功（get_by_username 内部 .lower()）
        result = await authenticate_user(db, "ALICE", "StrongP@ssW0rd")
        assert result is not None
        assert result.username == "alice"


@pytest.mark.asyncio
async def test_register_collapses_mixed_case_duplicate():
    """'Alice' 和 'alice' 在大小写不敏感 collation 下视为相同 → 第二次注册触发 unique 约束。

    SQLite 行为取决于 collation；这里通过 user_repo.create 内部 .lower() 归一保证
    跨方言一致——第二次注册必然撞 unique，路由层转 409。
    """
    # 首用户注册后放开 allow_registration，否则第二次会先撞 AUTH_REGISTRATION_DISABLED
    await get_config_store().set("auth.allow_registration", "true")
    async with SessionLocal() as db:
        async with db.begin():
            u1 = await register_user(db, "Alice", "StrongP@ssW0rd")
        assert u1.username == "alice"
        # 同一事务外第二次注册——username .lower() 后撞 unique，IntegrityError 抛给调用方
        async with SessionLocal() as db2:
            with pytest.raises(IntegrityError):
                async with db2.begin():
                    await register_user(db2, "ALICE", "StrongP@ssW0rd")
