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
async def test_mb_level_text_frame_rejected(monkeypatch):
    """issue #200：10 MB text frame 应被 4410 + frame_too_large 拦下。

    旧实现用 `len(payload) > self._max_frame_bytes` 校验，但作者实测用
    python-websockets 客户端发 10 MB text frame 仍被服务端 json.loads 解析
    通过 dispatch 路径，未触发 frame_too_large。新实现用累积 message
    size + UTF-8 字节计数（与 Uvicorn ws_max_size 字节预算对齐），单
    message 总字节超 _max_frame_bytes 立即 4410 关连接。
    """
    fake_ws = AsyncMock()
    # 模拟 1 MB text frame（10 MB 在 mock 环境下没必要，更小足够覆盖累积语义）
    big_text = "x" * (1024 * 1024)
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "text": big_text},
            {"type": "websocket.disconnect"},
        ]
    )
    handler = WSHandler(fake_ws, "sid")
    handler._max_frame_bytes = 64 * 1024  # 默认 64 KB

    fail_calls: list = []

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code, params))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await handler._loop()
    assert fail_calls == [("frame_too_large", 4410, {"max_kb": 64})]


@pytest.mark.asyncio
async def test_mb_level_binary_frame_rejected(monkeypatch):
    """issue #200：1 MB binary frame 应被 4410 + frame_too_large 拦下。

    binary frame 不经 UTF-8 编码，按 bytes 长度累积。
    """
    fake_ws = AsyncMock()
    big_bytes = b"x" * (1024 * 1024)
    fake_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "bytes": big_bytes},
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
