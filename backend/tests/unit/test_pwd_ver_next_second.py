"""pwd_ver 改密即吊销：跨同一秒边界严守。

历史 bug：int(timestamp()) 是秒级整数，注册与 admin 改密发生在同一秒内时，
旧 token 不被吊销（e2e 场景 D-2 飘红的根因）。

朴素「下一整秒（ceil）」也不行：ceil(27.300) == ceil(27.500) == 27，
两者撞同一整数秒还是相等。修复用进程内单调计数器：同一秒内多次调用，
后写整数严格大于先写整数；跨秒用 wall clock 触发下一基准。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.auth._pwd_ver_clock import (
    _reset_for_test,
    next_pwd_ver_ts,
    seed_from_db_max,
)


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


def test_unseeded_first_write_returns_floor():
    """未 seed 首写兜底：返回 int(now)（floor），无「最小步长」保证。

    风险点：进程重启后 _last=0、若调用方忘了 seed_from_db_max，
    首次写回退到 int(now)，可能跌穿已落库的更大值——见
    test_seeded_prevents_underflow_after_restart 守住正确路径。
    """
    t = datetime(2026, 8, 26, 2, 4, 27, 300_000, tzinfo=timezone.utc)
    v = int(next_pwd_ver_ts(t).timestamp())
    assert v == int(t.timestamp())  # 1787709867，与 docstring 一致


def test_seeded_prevents_underflow_after_restart():
    """seed 后首次写严格 > seed 值——守住进程重启场景。

    模拟：旧进程 T=27.900 写过 1787709868 落 DB，新进程重启后 _last=0；
    若不 seed，新进程 T=27.500 调用会回退到 1787709867（跌穿 1787709868，
    吊销放行）。
    """
    t = datetime(2026, 8, 26, 2, 4, 27, 500_000, tzinfo=timezone.utc)
    seed_from_db_max(1787709868)  # 启动期 lifespan 灌种子（DB 当前最大值）
    v = int(next_pwd_ver_ts(t).timestamp())
    assert v > 1787709868, f"seed=1787709868 后必须 > 1787709868，实际={v}"
    assert v == 1787709869


def test_seed_none_noop():
    """seed(None) → 空表跳过，_last 仍 0；下次调用走未 seed 首写分支。"""
    seed_from_db_max(None)
    t = datetime(2026, 8, 26, 2, 4, 27, 500_000, tzinfo=timezone.utc)
    v = int(next_pwd_ver_ts(t).timestamp())
    assert v == 1787709867


def test_seed_smaller_than_last_noop():
    """seed 值 ≤ _last 时不推 _last——避免重启后旧 seed 抹掉更大进度。

    first write 把 _last 推到 X；再 seed 一个 < X 的值后写 wall clock 时间，
    结果应基于 X（即 max(base, X+1)），证明 _last 没被小 seed 回退。
    """
    # 1) first write 用「未来时间」→ _last 推到大数 L
    future = datetime(2026, 8, 26, 2, 30, 0, 0, tzinfo=timezone.utc)
    L = int(next_pwd_ver_ts(future).timestamp())
    # 2) seed 一个比 L 小的值（模拟旧 seed 数据）
    seed_from_db_max(L - 1000)
    # 3) 再用较早时间 t 写：base=1787709867（小），但 _last 仍=L（seed 没回退）
    t = datetime(2026, 8, 26, 2, 4, 27, 500_000, tzinfo=timezone.utc)
    v = int(next_pwd_ver_ts(t).timestamp())
    assert v == L + 1, f"期望 L+1={L + 1}（基于 _last），实际 {v}"