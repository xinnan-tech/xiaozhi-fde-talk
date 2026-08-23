"""_drop_seed_admin：dev 自愈窄清理老种子 admin + demo_username 配置。

回归需求：老 bootstrap.seed_dev_users 会灌入 username='admin' role='admin' 的演示账号
+ auth.demo_username 配置项；自助注册体系不再允许这两个残留，
否则 registration-status 会卡死 / 首用户走不通。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.persistence.bootstrap import _drop_seed_admin
from app.persistence.db import SessionLocal
from app.persistence.models import SystemConfig, User


@pytest.fixture
async def _clean_users():
    """清掉 users 和 auth.demo_username 配置，避免上一个测试的状态泄漏。"""
    async with SessionLocal() as s:
        await s.execute(select(User).where(User.username.in_(["admin", "alice"])))
        # 直接用 text 清更稳，不依赖 ORM 缓存
        from sqlalchemy import text
        await s.execute(text("DELETE FROM users WHERE username IN ('admin', 'alice')"))
        await s.execute(text(
            "DELETE FROM system_config WHERE key = 'auth.demo_username'"
        ))
        await s.commit()
    yield
    async with SessionLocal() as s:
        from sqlalchemy import text
        await s.execute(text("DELETE FROM users WHERE username IN ('admin', 'alice')"))
        await s.execute(text(
            "DELETE FROM system_config WHERE key = 'auth.demo_username'"
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_drop_seed_admin_removes_only_admin_user(_clean_users):
    # seed：1 个 admin + 1 个普通用户
    async with SessionLocal() as s:
        s.add_all([
            User(id="u1", username="admin", password_hash="x", role="admin"),
            User(id="u2", username="alice", password_hash="x", role="user"),
        ])
        s.add(SystemConfig(key="auth.demo_username", value="admin"))
        await s.commit()

    await _drop_seed_admin()

    async with SessionLocal() as s:
        rows = (await s.execute(select(User))).scalars().all()
        usernames = {r.username for r in rows}
        # 只清 admin，alice 留着；其它残留用户（其它测试留下的）不动
        assert "admin" not in usernames
        assert "alice" in usernames
        cfg = (await s.execute(select(SystemConfig).where(
            SystemConfig.key == "auth.demo_username"
        ))).scalar_one_or_none()
        assert cfg is None


@pytest.mark.asyncio
async def test_drop_seed_admin_is_idempotent(_clean_users):
    await _drop_seed_admin()  # 第二次调用不报错
    await _drop_seed_admin()
