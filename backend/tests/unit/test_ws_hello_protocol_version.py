"""hello 回包必须带 protocol_version（握手与接管两条路径）。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.domain.session import SessionStatus
from app.transport.websocket import handler as h_mod
from app.transport.websocket.handler import WSHandler


def _mock_ws():
    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps(
        {"type": "hello", "client_id": "c1"}))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


async def test_handshake_hello_includes_protocol_version(monkeypatch):
    ws = _mock_ws()
    state = MagicMock()
    state.session.user_id = "u1"
    state.status = SessionStatus.CREATED

    async def _get(sid):
        return state

    async def _start(sid):
        return state

    monkeypatch.setattr(h_mod.manager, "get", _get)
    monkeypatch.setattr(h_mod.manager, "start", _start)

    rt = MagicMock()
    rt.bind = AsyncMock()
    rt._send_fn = None
    rt._bound_client_id = None
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)
    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda sid: False)

    h = WSHandler(ws, "s1")
    h._user = MagicMock(user_id="u1")
    assert await h._handshake()
    hello = ws.send_json.call_args[0][0]
    assert hello["type"] == "hello"
    assert hello["protocol_version"] == h_mod.PROTOCOL_VERSION == 1


async def test_takeover_hello_includes_protocol_version():
    ws = _mock_ws()
    rt = MagicMock()
    rt._fsm.is_terminated = False
    rt._send_fn = MagicMock()  # 已有 owner，本端是 pending
    rt.seq.resume_from_seq = 7

    h = WSHandler(ws, "s1")
    h.runtime = rt
    h.client_id = "c2"

    async def _takeover(send, client_id, evict, reason=""):
        pass

    rt.takeover = _takeover
    await h._on_takeover()

    hello = ws.send_json.call_args[0][0]
    assert hello["type"] == "hello"
    assert hello["protocol_version"] == h_mod.PROTOCOL_VERSION
    assert hello["resume_from_seq"] == 7
    assert hello["audio_params"] == {}
