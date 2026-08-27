"""E2E：5 个并发首用户注册 → DB 最多 1 个 admin。

首用户自动获 admin（service.register_user count==0 → role='admin'）。SQLite +
DEFERRED 事务下两个并发请求都见 count==0 → 两个都成 admin → 严重越权。
本测试用 BEGIN IMMEDIATE（SQLite 路径，见 auth.register 路由）锁首跳；
PG/MySQL 由默认隔离级别 + username unique 约束的 INSERT 排他锁自然串行化。

测试用 ASGITransport 在进程内跑完整 app + lifespan（与其他并发测试同款）。
不依赖外部 conftest.py（`--noconftest` 跑）。
"""
from __future__ import annotations

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.core.config_store import get_config_store
from app.persistence.db import SessionLocal
from app.persistence.models import User
from app.transport.http.routes.auth import _reset_for_test


@pytest.fixture(scope="module")
async def _lifespan_app():
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")
    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def empty_db(_lifespan_app):
    """函数级 fixture：清空 users + interviews + reports + auth.allow_registration。
    同时清空注册 / 登录限流桶（模块级 RateLimiter 跨用例持续累加）。
    """
    async def _wipe() -> None:
        async with SessionLocal() as s:
            async with s.begin():
                await s.execute(text("DELETE FROM reports"))
                await s.execute(text("DELETE FROM interviews"))
                await s.execute(text("DELETE FROM users"))
                await s.execute(
                    text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
                )

    await _wipe()
    get_config_store().invalidate()
    _reset_for_test()
    yield _lifespan_app
    await _wipe()
    get_config_store().invalidate()
    _reset_for_test()


async def _register(c: AsyncClient, username: str, password: str = "Strong1!pwd"):
    return await c.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
        },
    )


async def test_concurrent_first_user_register_at_most_one_admin(empty_db):
    """5 个并发 register + distinct username → DB admin 数 ≤ 1。

    理想态：1 admin + 4 user（第一个注册吃 count==0 → admin，其余被
    allow_registration=false 默认挡为 403，不进 DB；count==0 串行化保证）。

    退化态：SQLite + BEGIN IMMEDIATE 已落地本路由；本测试断言 admins ≤ 1 即可。
    退到 2+ admin 即视为回归，需排查并发首用户路径。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    usernames = [f"racer{i}" for i in range(5)]

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        results = await asyncio.gather(
            *[_register(c, u) for u in usernames],
            return_exceptions=True,
        )

    succeeded = 0
    rejected = 0
    for r in results:
        if isinstance(r, Exception):
            rejected += 1
            continue
        if r.status_code == 200:
            succeeded += 1
        else:
            rejected += 1

    # 直接查 DB 数 admin：硬约束不能超过 1
    async with SessionLocal() as s:
        admin_count = (await s.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )).scalar_one()
        user_count = (await s.execute(
            select(func.count(User.id)).where(User.role == "user")
        )).scalar_one()

    assert admin_count <= 1, (
        f"并发首注册：admin 数应 ≤ 1，实际 {admin_count}（succeeded={succeeded}，"
        f"rejected={rejected}，user_count={user_count}）"
    )
    # 5 个请求总账闭合：成功的 + 被拒的（含 403 allow_registration / 409 username / 429 限流 / 网络异常）= 5
    assert succeeded + rejected == 5, (
        f"5 次注册结果应闭合，实际 succeeded={succeeded} rejected={rejected}"
    )