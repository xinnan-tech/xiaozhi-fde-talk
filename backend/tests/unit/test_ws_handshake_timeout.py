"""· WS handshake 等首条 hello 加超时（C-010）。

客户端建连后不发 hello 时，原 _handshake 的 receive_text() 无超时，连接被无限期
挂住、资源累积。加 _handshake_timeout_s（默认 10s）超时：到点判 handshake_timeout、
close 4408。测试收窄超时到 0.05s，并用外层 wait_for 兜底抓住「未实现超时」的挂死。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import app.transport.websocket.handler as h_mod
from app.transport.websocket.handler import WSHandler


@pytest.mark.asyncio
async def test_handshake_timeout_closes_ws(monkeypatch):
    fake_ws = AsyncMock()

    async def _never_returns() -> str:
        await asyncio.sleep(100)  # 模拟不发 hello 的客户端

    fake_ws.receive_text = _never_returns

    handler = WSHandler(fake_ws, "sid")
    handler._handshake_timeout_s = 0.05  # 收窄，不等 10s
    fail_calls: list = []

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)

    # 外层兜底：若 handshake 未实现超时（bug），1s 后在此抓住，避免用例挂死
    try:
        result = await asyncio.wait_for(handler._handshake(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("handshake 缺少 hello 超时——客户端不发 hello 时挂死")

    assert result is False
    assert fail_calls == [("handshake_timeout", 4408)]
