"""单元测试：runtime → engine 事件接线（建段通知 / listen_stop 尾句收尾）。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.runtime import SessionRuntime
from app.services.sessions.state_machine import RuntimeState


def _runtime(make_state):
    rt = SessionRuntime(make_state())
    rt.engine = MagicMock()
    rt.engine.on_bind = MagicMock()
    rt.engine.on_utterance = MagicMock()
    rt.engine.on_listen_stopped = MagicMock()
    rt.pipeline = MagicMock()
    rt.pipeline.flush = AsyncMock()
    rt.pipeline.listen_start = AsyncMock()
    return rt


async def test_on_utterance_notifies_engine(make_state):
    rt = _runtime(make_state)
    rt._send_fn = AsyncMock()
    rt._fsm.transition(RuntimeState.LIVE)
    await rt._on_utterance("你好", True, 0)
    rt.engine.on_utterance.assert_called_once()


async def test_listen_stop_flushes_tail_then_final_recompute(make_state):
    """listen_stop：先停调度 → flush 管线（尾句入 transcript）→ 收尾重算 → 落盘。"""
    rt = _runtime(make_state)
    rt._send_fn = AsyncMock()
    from app.services.sessions.state_machine import RuntimeState
    rt._fsm.transition(RuntimeState.LIVE)
    order = []
    rt.engine.on_listen_pause.side_effect = lambda: order.append("pause")
    rt.pipeline.flush.side_effect = lambda: order.append("flush") or asyncio.sleep(0)
    rt.engine.on_listen_stopped.side_effect = lambda: order.append("stopped")
    await rt.listen_stop()
    assert order == ["pause", "flush", "stopped"]
