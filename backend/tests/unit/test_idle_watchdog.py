"""单元测试：SessionManager idle watchdog + activity tracking。

不依赖 DB（registry / _transition 用 monkeypatch 替换）；验证：
- touch / clear_activity 对 _active 的反应
- _suspend_idle 调 runtime.end + _transition + 清缓存
- _idle_watchdog_loop 对刚 touch 的会话不触发 suspend
"""
import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.manager import SessionManager


@pytest.fixture
def mgr():
    return SessionManager()


def _state(status="in_progress"):
    s = MagicMock()
    s.status = status
    s.session.id = "abcdef1234567890"
    s.session.user_id = "user00001111"
    return s


def test_touch_records_activity(mgr):
    mgr._active["abcdef1234567890"] = _state()
    mgr.touch("abcdef1234567890")
    assert "abcdef1234567890" in mgr._last_activity_at


def test_touch_ignores_unknown(mgr):
    mgr.touch("does-not-exist")  # 不抛异常
    assert "does-not-exist" not in mgr._last_activity_at


def test_clear_activity_removes_entry(mgr):
    mgr._active["abcdef1234567890"] = _state()
    mgr.touch("abcdef1234567890")
    mgr.clear_activity("abcdef1234567890")
    assert "abcdef1234567890" not in mgr._last_activity_at


@pytest.mark.asyncio
async def test_idle_suspend_calls_end_and_drops(mgr, monkeypatch):
    """模拟：会话 idle 超时 → _suspend_idle 触发 runtime.suspend + _active.pop。"""
    state = _state()
    mgr._active["abcdef1234567890"] = state
    mgr._last_activity_at["abcdef1234567890"] = time.monotonic() - 999

    runtime = MagicMock()
    runtime.suspend = AsyncMock()
    monkeypatch.setattr("app.services.sessions.manager.registry.get", lambda name: runtime)
    monkeypatch.setattr("app.services.sessions.manager.registry.drop", lambda name: None)

    # 替换为同步桩，避开 _transition 内部 DB 操作
    async def fake_transition(state, to):
        state.status = to
    monkeypatch.setattr(mgr, "_transition", fake_transition)

    await mgr._suspend_idle("abcdef1234567890", idle_for=200.0)

    runtime.suspend.assert_awaited_once()
    assert "abcdef1234567890" not in mgr._active
    assert "abcdef1234567890" not in mgr._last_activity_at


@pytest.mark.asyncio
async def test_idle_watchdog_skips_when_touched_recently(mgr):
    """最近 touch 过 → 不触发 suspend。"""
    state = _state()
    mgr._active["abcdef1234567890"] = state
    mgr._last_activity_at["abcdef1234567890"] = time.monotonic()  # 刚刚 touch

    calls = []
    async def fake_suspend(sid, idle_for):
        calls.append(sid)
    monkeypatch_suspend = pytest.MonkeyPatch()
    monkeypatch_suspend.setattr(mgr, "_suspend_idle", fake_suspend)

    # 跑一次 loop 切片（不等 sleep）
    task = asyncio.create_task(mgr._idle_watchdog_loop())
    await asyncio.sleep(0.05)  # 给 loop 一点时间跑第一轮
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    monkeypatch_suspend.undo()
    assert calls == []
