"""· _grace_expire 过期时清理 _active/_grace（不碰 registry）。

H2: 断线后不重连 → SUSPENDED 会话驻留 _active（含完整 SessionState）→ 内存无界增长。
分层不变量：_grace_expire 只清 manager 自己的账目，绝不调 registry.drop / runtime.end()。
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock

from app.domain.session import SessionStatus
from app.services.sessions.manager import SessionManager


@pytest.mark.asyncio
async def test_grace_expire_clears_active_and_does_not_touch_registry(monkeypatch):
    """_grace_expire 走完后：_active/_grace 清空，status 翻 SUSPENDED；
    且不调 registry.drop（分层不变量——runtime 销毁归 registry）。"""
    mgr = SessionManager()
    sid = "test-grace-1"

    state = MagicMock()
    state.status = SessionStatus.IN_PROGRESS
    mgr._active[sid] = state
    mgr._last_activity_at[sid] = 0.0

    # 避开 _transition 内部 DB 操作（沿用 test_idle_watchdog 的既定模式）
    transitioned: list[SessionStatus] = []

    async def fake_transition(s, to):
        s.status = to
        transitioned.append(to)

    monkeypatch.setattr(mgr, "_transition", fake_transition)

    # 守住分层不变量：监控 registry 是否被 _grace_expire 碰过
    drop_calls: list[str] = []
    monkeypatch.setattr(
        "app.services.sessions.manager.registry.drop",
        lambda name: drop_calls.append(name),
    )
    monkeypatch.setattr("app.services.sessions.manager.registry.get", lambda name: None)

    # 短 grace 加速触发
    async def fake_cfg():
        return {"grace_period_s": 0.05, "idle_timeout_s": 120.0, "idle_check_interval_s": 30.0}

    monkeypatch.setattr(
        "app.services.sessions.manager.get_session_runtime_config", fake_cfg
    )

    await mgr.on_disconnect(sid)        # 启动 _grace_expire
    await asyncio.sleep(0.2)            # 等过期（grace 0.05s + 余量）

    assert sid not in mgr._active, f"_active 仍残留: {list(mgr._active.keys())}"
    assert sid not in mgr._grace, f"_grace 仍残留: {list(mgr._grace.keys())}"
    assert transitioned == [SessionStatus.SUSPENDED], f"应翻 SUSPENDED，实得 {transitioned}"
    # 分层不变量：_grace_expire 绝不碰 registry（ASR/LLM 实例归 registry._expire 销毁）
    assert drop_calls == [], f"_grace_expire 不应调 registry.drop，实得 {drop_calls}"
