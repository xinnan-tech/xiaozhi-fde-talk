"""P1-4 · registry._expire 的 end() 与重连竞态（M1）。

_expire 流程先从 _parked pop，再调 runtime.end()（含 LLM 终算，秒级）。期间该
session 既不在 _active 也不在 _parked，并发重连 get_or_create 会落空 → 新建一个
孤儿 runtime 漏进 _active 且无人回收。

方案 (a)：_expire 在 end() 期间把 session 标记进 terminating 集合；handler 重连
路径在 get_or_create 之前检查 is_terminating，命中则拒绝（session_ended/4406）。

窗口不变量：terminating 仅在 liveness_window_s 已过、_expire 触发后才非空，
故"重连被拒"只发生在用户已断开 ≥ liveness_window_s 之后——按定义已非临时断开。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.session import Session, SessionStatus
from app.services.sessions.runtime import RuntimeRegistry, SessionRuntime
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template
from app.transport.websocket.handler import WSHandler


def _make_runtime(sid: str) -> SessionRuntime:
    tpl = get_template("pm-research")
    session = Session(id=sid, template_id="pm-research", status=SessionStatus.IN_PROGRESS)
    return SessionRuntime(state=SessionState.initial(session, tpl))


@pytest.mark.asyncio
async def test_expire_marks_terminating_during_end():
    """_expire 在 runtime.end() 期间必须把 session 标记为 terminating。

    用 Event 门控 end()：end() 启动即置位 end_started、阻塞等 end_can_finish，
    断言窗口内 is_terminating 为真；放行后终止标记清除。无计时竞态。
    """
    reg = RuntimeRegistry()
    sid = "race-1"
    rt = _make_runtime(sid)

    end_started = asyncio.Event()
    end_can_finish = asyncio.Event()

    async def slow_end():
        end_started.set()
        await end_can_finish.wait()

    rt.end = slow_end  # 实例属性遮蔽方法

    # ttl_s=0 → _expire 立即过 sleep 进入 end()
    reg.park(sid, rt, ttl_s=0.0)
    await end_started.wait()

    assert reg.is_terminating(sid), "end() 期间必须标记 terminating，否则重连漏建孤儿 runtime"

    end_can_finish.set()
    # 等 _expire 跑完 finally 清除终止标记（end() 完成后必然）
    for _ in range(50):
        if not reg.is_terminating(sid):
            break
        await asyncio.sleep(0.01)
    assert not reg.is_terminating(sid), "end() 完成后应清除 terminating 标记"


@pytest.mark.asyncio
async def test_reconnect_during_terminating_is_rejected(monkeypatch):
    """end() 进行中的会话重连必须被拒，且不得调 get_or_create（避免孤儿 runtime）。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": []}
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps({"type": "hello"}))

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.status = SessionStatus.IN_PROGRESS
    monkeypatch.setattr("app.transport.websocket.handler.manager.get", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(
        "app.transport.websocket.handler.manager.on_reconnect", AsyncMock(return_value=fake_state)
    )

    # registry 处于 terminating：is_terminating True；get_or_create 不应被调
    fake_registry = MagicMock()
    fake_registry.is_terminating = MagicMock(return_value=True)
    fake_registry.get_or_create = MagicMock()
    monkeypatch.setattr("app.transport.websocket.handler.registry", fake_registry)

    h = WSHandler(ws, "race-sid")
    h._user = SimpleNamespace(user_id="u1")  # 鉴权在 run() 的 accept 之前完成
    ok = await h._handshake()

    assert ok is False
    sent = ws.send_json.call_args[0][0]
    assert sent["code"] == "session_ended", sent
    ws.close.assert_awaited_once_with(code=4406)
    fake_registry.get_or_create.assert_not_called()
