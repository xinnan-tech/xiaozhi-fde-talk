"""P1-3 · 在线 runtime 生命周期集成测试（handler 与 shutdown 层）。

解耦契约（spec 铁律1）：WS 断开 → runtime 从 _active 移入 _parked（寄存，不销毁）；
liveness 窗口内重连 → 复用同一 runtime。_active 的移除由 park/drop 内部完成，
handler 不直接调 unregister（否则 park 前会出现 runtime 既不在 _active 也不在 _parked
的空窗，重连 get_or_create 落空 → 新建 runtime → ASR/LLM 重实例化，解耦被破坏）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.session import Session, SessionStatus
from app.services.sessions import manager as manager_mod
from app.services.sessions.runtime import RuntimeRegistry, SessionRuntime
from app.services.sessions.state_machine import RuntimeState
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template
from app.transport.websocket.handler import WSHandler


def _make_runtime(sid: str) -> SessionRuntime:
    tpl = get_template("pm-research")
    session = Session(id=sid, template_id="pm-research", status=SessionStatus.IN_PROGRESS)
    return SessionRuntime(state=SessionState.initial(session, tpl))


@pytest.mark.asyncio
async def test_cleanup_parks_runtime_without_destroying(monkeypatch):
    """临时断连：_cleanup 必须把 runtime 从 _active 移入 _parked（寄存），不得销毁。

    断连后重连窗口内 get_or_create 必须能取回同一对象——前提是 park 先于任何销毁。
    handler 不调 unregister：否则会在 unregister 与 park 之间出现空窗。
    """
    reg = RuntimeRegistry()
    monkeypatch.setattr("app.transport.websocket.handler.registry", reg)
    sid = "cleanup-1"
    rt = _make_runtime(sid)
    reg.register(sid, rt)  # 模拟 bind 后的在线状态
    assert reg.get_active(sid) is rt

    handler = WSHandler(ws=MagicMock(), session_id=sid)
    handler.runtime = rt
    # owner 守卫要求：只有当前绑定的 handler 才能拆绑（runtime._send_fn 指向它）
    rt._send_fn = handler._send

    # 隔离真实副作用：unbind（flush/ASR）与 manager.on_disconnect（DB）。
    # 真实 unbind 会把 _send_fn 置回 None——_cleanup 的重连复查依赖这一点。
    async def _fake_unbind(_send):
        rt._send_fn = None
        return True
    monkeypatch.setattr(rt, "unbind", _fake_unbind)
    monkeypatch.setattr(manager_mod.manager, "on_disconnect", AsyncMock())

    await handler._cleanup()

    # runtime 被寄存，未被销毁：_active 清空、_parked 持有同一对象
    assert reg.get_active(sid) is None, "断连后 _active 不应残留"
    assert reg.get(sid) is rt, "断连后 runtime 应寄存在 _parked，可被重连取回"

    reg.drop(sid)  # 清理定时器


@pytest.mark.asyncio
async def test_shutdown_drain_covers_active_and_parked():
    """shutdown drain（all_runtimes）必须覆盖 _active 与 _parked 全部 runtime。"""
    reg = RuntimeRegistry()
    rt1 = _make_runtime("active-1")
    rt2 = _make_runtime("parked-1")
    rt1.shutdown_quick = AsyncMock()
    rt2.shutdown_quick = AsyncMock()
    reg.register("active-1", rt1)
    reg.register("parked-1", rt2)
    reg.park("parked-1", rt2, ttl_s=60.0)  # rt2 进 _parked

    # app.py shutdown 的等价逻辑：all_runtimes() 汇总 active+parked
    for rt in reg.all_runtimes():
        await rt.shutdown_quick()

    rt1.shutdown_quick.assert_awaited_once()
    rt2.shutdown_quick.assert_awaited_once()
    reg.drop("parked-1")


@pytest.mark.asyncio
async def test_handler_ended_path_drops_runtime(monkeypatch):
    """会话已结束时断连：_cleanup 的 park 对 TERMINATED runtime 不寄存、直接 drop。

    end 由 REST 的后台拆除（rt.end()）执行并置 TERMINATED；在线连接随后断开，
    其 _cleanup 不得把已销毁的 runtime 寄存回 _parked。
    """
    reg = RuntimeRegistry()
    monkeypatch.setattr("app.transport.websocket.handler.registry", reg)
    sid = "ended-1"
    rt = _make_runtime(sid)
    reg.register(sid, rt)
    # 模拟后台 rt.end() 已跑完：runtime 置 TERMINATED（此后端会话已结束）
    rt._fsm.transition(RuntimeState.TERMINATED)

    handler = WSHandler(ws=MagicMock(), session_id=sid)
    handler.runtime = rt
    rt._send_fn = handler._send

    async def _fake_unbind(_send):
        rt._send_fn = None
        return True
    monkeypatch.setattr(rt, "unbind", _fake_unbind)

    await handler._cleanup()

    # TERMINATED 不寄存：账目彻底清除
    assert reg.get(sid) is None, "end 后 runtime 应被彻底清除"
    assert reg.get_active(sid) is None
