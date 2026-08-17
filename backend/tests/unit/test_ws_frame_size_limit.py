"""P3-6 · WS 单帧大小限制 64KB（M-015）。

原 _loop 收到任意大小帧都直接处理，客户端发超大帧（恶意或失控）会吞内存/拖垮解析。
加 _max_frame_bytes（默认 64KB）上限：text/bytes 任一 payload 超限即判
frame_too_large、close 4410（4409 专属并发上限）。测试收窄上限到 64 字节。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.transport.websocket.handler import WSHandler


@pytest.mark.asyncio
async def test_oversized_bytes_frame_rejected():
    fake_ws = AsyncMock()
    big = b"x" * 100
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "bytes": big},
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64  # 收窄

    fail_calls: list = []

    async def fake_fail(code: str, message: str, close_code: int = 4000) -> None:
        fail_calls.append((code, close_code))

    handler._fail = fake_fail
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410)]


@pytest.mark.asyncio
async def test_oversized_text_frame_rejected():
    fake_ws = AsyncMock()
    big_text = "x" * 100
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "text": big_text},
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64

    fail_calls: list = []

    async def fake_fail(code: str, message: str, close_code: int = 4000) -> None:
        fail_calls.append((code, close_code))

    handler._fail = fake_fail
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410)]


@pytest.mark.asyncio
async def test_normal_size_frame_not_rejected():
    fake_ws = AsyncMock()
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "bytes": b"abcd"},  # < limit
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64

    fail_calls: list = []

    async def fake_fail(code: str, message: str, close_code: int = 4000) -> None:
        fail_calls.append((code, close_code))

    handler._fail = fake_fail
    await handler._loop()
    assert fail_calls == []
