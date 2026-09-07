"""· WS 单帧大小限制 64KB（M-015）。

原 _loop 收到任意大小帧都直接处理，客户端发超大帧（恶意或失控）会吞内存/拖垮解析。
加 _max_frame_bytes（默认 64KB）上限：text/bytes 任一 payload 超限即判
frame_too_large、close 4410（4409 专属并发上限）。测试收窄上限到 64 字节。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import app.transport.websocket.handler as h_mod
from app.transport.websocket.handler import WSHandler


@pytest.mark.asyncio
async def test_oversized_bytes_frame_rejected(monkeypatch):
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

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410)]


@pytest.mark.asyncio
async def test_oversized_text_frame_rejected(monkeypatch):
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

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410)]


@pytest.mark.asyncio
async def test_normal_size_frame_not_rejected(monkeypatch):
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

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == []


@pytest.mark.asyncio
async def test_utf8_byte_counting_text_frame(monkeypatch):
    """UTF-8 字节计数边界：30000 个中文字符 = 90000 字节 > 64 KB 上限。

    旧实现按 `len(text) > self._max_frame_bytes` 用字符数判，30000 字符 <
    64 K 上限会被放过。新实现按 `len(text.encode("utf-8"))` 字节判，90000
    字节 > 64 K 立即 4410 关连接。
    """
    fake_ws = AsyncMock()
    # 30000 个中文字符 = 30000 * 3 = 90000 UTF-8 字节 > 64 * 1024 = 65536
    big_text = "中" * 30000
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "text": big_text},
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64 * 1024

    fail_calls: list = []

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code, params))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410, {"max_kb": 64})]


@pytest.mark.asyncio
async def test_max_kb_floor_when_limit_sub_kb(monkeypatch):
    """_max_frame_bytes < 1 KB 时 max_kb 应向上取整到 1，前端 i18n 文案不显示「0 KB」。
    """
    fake_ws = AsyncMock()
    big = b"x" * 100
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "bytes": big},
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64  # 64 字节 < 1 KB

    fail_calls: list = []

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code, params))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410, {"max_kb": 1})]
