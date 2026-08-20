"""WSHandler._dispatch：session.touch 帧 → manager.touch(session_id)，
且不碰 ASR / 引擎 / 管线。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.transport.websocket.handler import WSHandler
from app.core.constants import WsMsgType


@pytest.fixture
def handler(monkeypatch):
    """构造一个 minimal WSHandler：runtime 设上，_send 绑定自身。"""
    ws = MagicMock()
    h = WSHandler(ws, "sid")
    rt = MagicMock()
    rt._send_fn = h._send  # ownership 守卫通过
    rt._bound_client_id = "clientA"
    h.runtime = rt
    return h


async def test_touch_calls_manager_touch(handler, monkeypatch):
    touched: list[str] = []
    import app.transport.websocket.handler as handler_mod
    monkeypatch.setattr(handler_mod.manager, "touch",
                        lambda sid: touched.append(sid))

    await handler._dispatch({"type": WsMsgType.SESSION_TOUCH})
    assert touched == ["sid"]


async def test_touch_does_not_call_listen_start(handler, monkeypatch):
    """session.touch 必须是无副作用帧：不应触发 listen_start / 任何管线动作。"""
    listened: list[str] = []
    import app.transport.websocket.handler as handler_mod
    monkeypatch.setattr(handler_mod.manager, "touch",
                        lambda sid: None)
    monkeypatch.setattr(handler.runtime, "listen_start",
                        AsyncMock(side_effect=lambda: listened.append("start")))

    await handler._dispatch({"type": WsMsgType.SESSION_TOUCH})
    assert listened == []


async def test_touch_is_no_op_when_not_owner(handler, monkeypatch):
    """被踢的旧连接发 touch：ownership 守卫直接 return，不重置新 owner 的计时器。"""
    handler.runtime._send_fn = MagicMock()  # 不是当前 owner
    touched: list[str] = []
    import app.transport.websocket.handler as handler_mod
    monkeypatch.setattr(handler_mod.manager, "touch",
                        lambda sid: touched.append(sid))

    await handler._dispatch({"type": WsMsgType.SESSION_TOUCH})
    assert touched == []