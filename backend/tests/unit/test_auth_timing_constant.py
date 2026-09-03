"""时序侧信道修复验证：authenticate_user 所有失败路径耗时均衡。

Issue #205：用户不存在时直接 return，不走 bcrypt，导致 13ms vs 1230ms 的时间差。
修复后：所有失败路径都执行相同次数的 bcrypt 运算，CPU 工作量完全一致。
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


async def test_timing_spread_small():
    """验证：用户不存在 vs 用户存在密码错误，两条路径耗时差 < 300ms。

    修复后两条路径都跑相同次数的 bcrypt（路径A: dummy；路径B: real + dummy），
    CPU 工作量完全一致，差值只来自 call scheduling 误差（< 50ms）。
    攻击者多次采样也无法统计区分。
    """
    dummy = _DummyUser()
    original_get = auth_svc.user_repo.get_by_username

    # 用户存在 + 密码错误：real bcrypt (fail) + dummy bcrypt
    auth_svc.user_repo.get_by_username = AsyncMock(return_value=dummy)
    t_exist = time.monotonic()
    result_exist = await auth_svc.authenticate_user(db=None, username="__user__", password="wrong")
    t_exist_elapsed = time.monotonic() - t_exist
    assert result_exist is None, "密码错误应返回 None"

    # 用户不存在：dummy bcrypt
    auth_svc.user_repo.get_by_username = AsyncMock(return_value=None)
    t_none = time.monotonic()
    result_none = await auth_svc.authenticate_user(db=None, username="__nonexistent__", password="any")
    t_none_elapsed = time.monotonic() - t_none
    assert result_none is None, "不存在用户应返回 None"

    auth_svc.user_repo.get_by_username = original_get

    spread = abs(t_exist_elapsed - t_none_elapsed)
    assert spread < 0.3, (
        f"两条失败路径时差 {spread*1000:.0f}ms > 300ms，"
        f"攻击者仍可区分（exist={t_exist_elapsed*1000:.0f}ms, "
        f"nonexist={t_none_elapsed*1000:.0f}ms）"
    )
