"""· ASR WS 启用 ping_interval/ping_timeout，检测死连接（C-004）。

原 connect_kwargs 显式 ping_interval=None / ping_timeout=None，禁用了 websockets
内置心跳。ASR 服务端半挂（TCP 连接在但对面不回）时，客户端永远收不到 EOF，feed
持续静默失败、asr 假活。启用 ping_interval=20 / ping_timeout=10：20s 一个 ping，
10s 内无 pong 即判定连接死，触发底层关闭。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import app.adapters.asr.funasr_server as funasr_mod


@pytest.mark.asyncio
async def test_start_stream_enables_ping():
    provider = funasr_mod.FunASRServerProvider()
    provider._ws_url = "ws://localhost:10096"

    fake_ws = AsyncMock()  # send(init_msg) 成功
    mock_connect = AsyncMock(return_value=fake_ws)

    with patch.object(funasr_mod.websockets, "connect", new=mock_connect):
        await provider.start_stream(AsyncMock())

    # 清理：start_stream 起的后台 _recv_task
    if provider._recv_task is not None:
        provider._recv_task.cancel()
        try:
            await provider._recv_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    kwargs = mock_connect.call_args.kwargs
    assert kwargs.get("ping_interval") == 20, (
        f"应启用 ping_interval=20，got {kwargs.get('ping_interval')!r}"
    )
    assert kwargs.get("ping_timeout") == 10, (
        f"应启用 ping_timeout=10，got {kwargs.get('ping_timeout')!r}"
    )


@pytest.mark.asyncio
async def test_start_stream_does_not_pass_proxy_kwarg():
    """确保 kwargs 不再含 proxy（#136）。"""
    provider = funasr_mod.FunASRServerProvider()
    provider._ws_url = "ws://localhost:10096"

    fake_ws = AsyncMock()  # send(init_msg) 成功
    mock_connect = AsyncMock(return_value=fake_ws)

    with patch.object(funasr_mod.websockets, "connect", new=mock_connect):
        await provider.start_stream(AsyncMock())

    if provider._recv_task is not None:
        provider._recv_task.cancel()
        try:
            await provider._recv_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    kwargs = mock_connect.call_args.kwargs
    assert "proxy" not in kwargs, (
        f"不应向 websockets.connect() 传 proxy kwarg（会 TypeError），got {sorted(kwargs)!r}"
    )
