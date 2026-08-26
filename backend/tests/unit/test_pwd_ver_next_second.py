"""pwd_ver 改密即吊销：跨秒边界严守。

历史 bug：int(timestamp()) 是秒级整数，注册与改密发生在同一秒内时，
旧 token 不被吊销（e2e 场景 D-2 飘红的根因）。修复后：改密路径写
password_changed_at = next_pwd_ver_ts()（下一整秒），保证 int 严格 >
旧 token 的 pwd_ver。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.auth._pwd_ver_clock import next_pwd_ver_ts


def test_same_second_change_strictly_increases():
    """注册 t1、改密 t1+0.3s（同一秒）：改密后 pwd_ver = t1+1s 整。"""
    t1 = datetime(2026, 8, 26, 2, 4, 27, 300_000, tzinfo=timezone.utc)
    pwd_ver_register = int(t1.timestamp())
    after = next_pwd_ver_ts(t1)
    pwd_ver_after = int(after.timestamp())
    assert pwd_ver_after == pwd_ver_register + 1
    assert pwd_ver_after > pwd_ver_register


def test_already_on_second_boundary_ceils_up():
    """整秒边界：ts=02:04:27.000000 → 仍写 02:04:28（ceil 而非 floor）。

    关键边界——若退化成 floor（等于自己），admin 在第 N 秒最后一刻改密，
    旧 token 的 pwd_ver = int(N) 与改密后 int(N) 相等，放行；用户能继续用
    旧密码登录后的 token。这一条守住就堵住这个洞。
    """
    t = datetime(2026, 8, 26, 2, 4, 27, 0, tzinfo=timezone.utc)
    after = next_pwd_ver_ts(t)
    assert int(after.timestamp()) == int(t.timestamp()) + 1  # 02:04:28


def test_near_boundary_microseconds_ceils_up():
    """亚秒边界：02:04:27.999999 → 02:04:28。"""
    t = datetime(2026, 8, 26, 2, 4, 27, 999_999, tzinfo=timezone.utc)
    after = next_pwd_ver_ts(t)
    assert int(after.timestamp()) == int(t.timestamp()) + 1


def test_returns_aware_utc_datetime():
    """返回值必须是 aware UTC——存库时不能因为 tzinfo=None 飘移到本地时区。"""
    t = datetime.now(timezone.utc)
    after = next_pwd_ver_ts(t)
    assert after.tzinfo is not None
    assert after.utcoffset().total_seconds() == 0


def test_default_now_uses_current_time():
    """不传参 → 用 datetime.now(utc) 走同样的 ceil 路径。"""
    before = int(datetime.now(timezone.utc).timestamp())
    after = next_pwd_ver_ts()
    pwd_ver_after = int(after.timestamp())
    # before ≤ pwd_ver_after ≤ before + 1（最多 +1 秒）
    assert before <= pwd_ver_after <= before + 1