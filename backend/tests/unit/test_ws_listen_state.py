"""listen.state 未知值（拼写错误等）必须忽略，不得误当 stop 停麦。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.transport.websocket.handler import WSHandler


def _handler_with_runtime():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    h = WSHandler(ws, "s1")
    h.runtime = MagicMock()
    h.runtime._send_fn = h._send  # 通过 ownership 守卫
    h.runtime.listen_start = AsyncMock()
    h.runtime.listen_stop = AsyncMock()
    return h


async def test_listen_states_route_correctly():
    h = _handler_with_runtime()
    await h._dispatch(json.loads('{"type": "listen", "state": "start"}'))
    h.runtime.listen_start.assert_awaited_once()
    await h._dispatch(json.loads('{"type": "listen", "state": "stop"}'))
    h.runtime.listen_stop.assert_awaited_once()


async def test_listen_unknown_state_is_ignored():
    h = _handler_with_runtime()
    for bad in ("Stop", "", None, 1):
        await h._dispatch({"type": "listen", "state": bad})
    h.runtime.listen_start.assert_not_awaited()
    h.runtime.listen_stop.assert_not_awaited()
