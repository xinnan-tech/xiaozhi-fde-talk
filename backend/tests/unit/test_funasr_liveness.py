from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import websockets

from app.adapters.asr.funasr_server import FunASRServerProvider
from app.core.exceptions import ASRProviderError


async def test_recv_loop_marks_ws_dead_on_close():
    """recv_loop 结束 → 连接判死（is_alive False + _ws_dead），但句柄保留供 close()。"""
    p = FunASRServerProvider()
    p.on_dead = AsyncMock()
    p._ws = AsyncMock()
    p._ws.recv = AsyncMock(side_effect=websockets.ConnectionClosed(None, None))
    p._parse_response = AsyncMock(return_value=False)
    await p._recv_loop()
    assert p._ws is not None
    assert p._ws_dead is True
    assert p.is_alive is False
    p.on_dead.assert_awaited_once()


async def test_feed_stream_raises_when_ws_dead():
    p = FunASRServerProvider()
    p._ws = None
    try:
        await p.feed_stream(b"\x00" * 10)
        assert False, "应抛 ASRProviderError"
    except ASRProviderError:
        pass


async def test_recv_loop_no_on_dead_on_intentional_stop():
    """主动 stop_stream（_is_stopping=True）→ recv_loop 退出不触发 on_dead（非假活）。"""
    p = FunASRServerProvider()
    p.on_dead = AsyncMock()
    p._ws = AsyncMock()
    p._is_stopping = True
    p._ws.recv = AsyncMock(side_effect=asyncio.CancelledError())
    p._parse_response = AsyncMock(return_value=False)
    try:
        await p._recv_loop()
    except asyncio.CancelledError:
        pass
    assert p._ws_dead is True
    assert p.is_alive is False
    p.on_dead.assert_not_awaited()
