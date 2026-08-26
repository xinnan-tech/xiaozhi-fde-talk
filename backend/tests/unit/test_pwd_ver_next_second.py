"""pwd_ver 改密即吊销：跨同一秒边界严守。

历史 bug：int(timestamp()) 是秒级整数，注册与 admin 改密发生在同一秒内时，
旧 token 不被吊销（e2e 场景 D-2 飘红的根因）。

朴素「下一整秒（ceil）」也不行：ceil(27.300) == ceil(27.500) == 27，
两者撞同一整数秒还是相等。修复用进程内单调计数器：同一秒内多次调用，
后写整数严格大于先写整数；跨秒用 wall clock 触发下一基准。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.auth._pwd_ver_clock import _reset_for_test, next_pwd_ver_ts


def setup_function(_):
    """每个用例前清零计数器，避免用例间污染。"""
    _reset_for_test()


def test_same_second_change_strictly_increases():
    """注册 27.300、改密 27.500（同一秒）：改密后 int 严格 > 注册 int。"""
    t_reg = datetime(2026, 8, 26, 2, 4, 27, 300_000, tzinfo=timezone.utc)
    t_reset = datetime(2026, 8, 26, 2, 4, 27, 500_000, tzinfo=timezone.utc)

    pwd_after_reg = int(next_pwd_ver_ts(t_reg).timestamp())
    pwd_after_reset = int(next_pwd_ver_ts(t_reset).timestamp())

    assert pwd_after_reset == pwd_after_reg + 1
    assert pwd_after_reset > pwd_after_reg


def test_triple_call_within_same_second_monotonic():
    """同一秒三次：第二次、第三次必须严格大于前一次。"""
    t = datetime(2026, 8, 26, 2, 4, 27, 100_000, tzinfo=timezone.utc)
    v1 = int(next_pwd_ver_ts(t).timestamp())
    v2 = int(next_pwd_ver_ts(t).timestamp())
    v3 = int(next_pwd_ver_ts(t).timestamp())
    assert v1 < v2 < v3, f"strict monotonic: got {v1},{v2},{v3}"


def test_cross_second_uses_wall_clock():
    """跨秒：用 wall clock 推进下一基准，不依赖计数器。"""
    t1 = datetime(2026, 8, 26, 2, 4, 27, 999_999, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 26, 2, 4, 28, 0, tzinfo=timezone.utc)
    v1 = int(next_pwd_ver_ts(t1).timestamp())
    v2 = int(next_pwd_ver_ts(t2).timestamp())
    assert v1 < v2


def test_returns_aware_utc_datetime():
    """返回值必须是 aware UTC——存库时不能因为 tzinfo=None 飘移到本地时区。"""
    t = datetime.now(timezone.utc)
    after = next_pwd_ver_ts(t)
    assert after.tzinfo is not None
    assert after.utcoffset().total_seconds() == 0


def test_default_now_uses_current_time():
    """不传参 → 走 datetime.now(utc) + 计数器。"""
    before = int(datetime.now(timezone.utc).timestamp())
    after = next_pwd_ver_ts()
    pwd_ver_after = int(after.timestamp())
    # before ≤ pwd_ver_after ≤ before + 1（同一秒内最多 +1）
    assert before <= pwd_ver_after <= before + 1