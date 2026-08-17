from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import IllegalTransitionError
from app.domain.session import SessionStatus
from app.transport.websocket.handler import WSHandler


async def test_internal_error_does_not_leak_detail(monkeypatch):
    """内部异常回前端的 message 不含 str(e)。"""
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=RuntimeError("DB password=hunter2"))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    user = MagicMock()
    user.user_id = "u1"
    monkeypatch.setattr(h_mod, "extract_auth", lambda t: user)
    h = WSHandler(ws, "s1")
    # _handshake 抛内部异常 → run 的兜底 except
    await h.run()
    sent = ws.send_json.call_args[0][0]
    assert sent["code"] == "internal"
    assert "hunter2" not in sent["message"]
    assert sent["message"]  # 有友好文案


async def test_bad_token_rejected_before_accept():
    """坏 token：accept 之前直接拒绝握手，不进消息循环占资源。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.not-a-jwt"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    h = WSHandler(ws, "s1")
    await h.run()
    ws.accept.assert_not_awaited()
    ws.receive_text.assert_not_awaited()
    ws.close.assert_awaited_once()


async def test_missing_token_rejected_before_accept():
    """无 token 子协议：同样在 accept 之前被拒。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": []}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    h = WSHandler(ws, "s1")
    await h.run()
    ws.accept.assert_not_awaited()
    ws.receive_text.assert_not_awaited()
    ws.close.assert_awaited_once()


async def test_handshake_on_ended_session_returns_4406(monkeypatch):
    """连接已结束的访谈：session_ended + 4406，而非漏成 internal + 4000。"""
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps(
        {"type": "hello", "client_id": "c1"}))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    state = MagicMock()
    state.session.user_id = "u1"
    state.status = SessionStatus.ENDED

    async def _get(sid):
        return state

    async def _start(sid):
        raise IllegalTransitionError("非法状态转换: ended → in_progress")

    monkeypatch.setattr(h_mod.manager, "get", _get)
    monkeypatch.setattr(h_mod.manager, "start", _start)

    h = WSHandler(ws, "s1")
    h._user = MagicMock(user_id="u1")  # run() 已在 accept 前完成鉴权
    assert not await h._handshake()
    sent = ws.send_json.call_args[0][0]
    assert sent["code"] == "session_ended"
    assert ws.close.call_args.kwargs["code"] == 4406
