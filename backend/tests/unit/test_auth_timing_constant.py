"""时序侧信道修复验证：authenticate_user 所有失败路径耗时均衡。

Issue #205：用户不存在时直接 return，不走 bcrypt，导致 13ms vs 1230ms 的时间差。
修复后：用户不存在路径 sleep(0.9~1.3s)，使所有失败路径均落在同一时间区间。
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import bcrypt

from app.services.auth import service as auth_svc


class _DummyUser:
    """仿造 User ORM 对象。"""
    def __init__(self):
        self.id = "dummy-id"
        self.username = "dummy"
        self.role = "user"
        self.password_hash = bcrypt.hashpw(b"dummy_password", bcrypt.gensalt()).decode()


async def test_nonexistent_user_sleeps(monkeypatch):
    """验证：不存在的用户名触发 ~0.9~1.3s sleep，使响应时间与真实密码校验路径对齐。"""
    monkeypatch.setattr(
        auth_svc.user_repo, "get_by_username",
        AsyncMock(return_value=None),
    )
    t0 = time.monotonic()
    result = await auth_svc.authenticate_user(db=None, username="__nonexistent__", password="wrong")
    elapsed = time.monotonic() - t0
    assert result is None, "不存在用户应返回 None"
    assert 0.8 < elapsed < 1.5, (
        f"不存在用户路径耗时 {elapsed*1000:.0f}ms 不在 [800ms, 1500ms] 区间，"
        "说明 sleep 未生效或已被优化掉"
    )


async def test_wrong_password_runs_bcrypt(monkeypatch):
    """验证：用户存在但密码错误时走真实 bcrypt（已有行为，回归保护）。"""
    monkeypatch.setattr(
        auth_svc.user_repo, "get_by_username",
        AsyncMock(return_value=_DummyUser()),
    )
    t0 = time.monotonic()
    result = await auth_svc.authenticate_user(db=None, username="__real_user__", password="wrong_password")
    elapsed = time.monotonic() - t0
    assert result is None, "密码错误应返回 None"
    # bcrypt ~200ms + sleep 0.9~1.3s → 总量 ~1.1~1.5s
    assert 0.8 < elapsed < 1.5, (
        f"错误密码路径耗时 {elapsed*1000:.0f}ms 不在 [800ms, 1500ms] 区间"
    )


async def test_timing_spread_small():
    """验证：用户不存在 vs 用户存在密码错误，两条路径耗时差 < 400ms。

    攻击者需区分两个区间（修复前 13ms vs 1230ms，差值 100x）。
    修复后两者都在 [0.8s, 1.5s] 区间，差值 < 400ms 则攻击失效。
    """
    dummy = _DummyUser()
    # 先测不存在路径
    original_get = auth_svc.user_repo.get_by_username
    auth_svc.user_repo.get_by_username = AsyncMock(return_value=None)
    try:
        t_none = time.monotonic()
        result_none = await auth_svc.authenticate_user(db=None, username="__x__", password="any")
        t_none_elapsed = time.monotonic() - t_none
        assert result_none is None
    finally:
        auth_svc.user_repo.get_by_username = original_get

    # 再测存在用户但密码错误路径
    auth_svc.user_repo.get_by_username = AsyncMock(return_value=dummy)
    try:
        t_exist = time.monotonic()
        result_exist = await auth_svc.authenticate_user(db=None, username="__y__", password="wrong")
        t_exist_elapsed = time.monotonic() - t_exist
        assert result_exist is None
    finally:
        auth_svc.user_repo.get_by_username = original_get

    spread = abs(t_exist_elapsed - t_none_elapsed)
    assert spread < 0.4, (
        f"两条失败路径时差 {spread*1000:.0f}ms > 400ms，"
        f"攻击者仍可区分（exist={t_exist_elapsed*1000:.0f}ms, "
        f"nonexist={t_none_elapsed*1000:.0f}ms）"
    )
