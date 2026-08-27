"""· start_stream 在 send init_msg 失败时关闭已建立的 WS 连接，不泄漏句柄。

start_stream 先 await websockets.connect(...)（建立 self._ws），再 send(init_msg)。
若 send 失败，原代码 except 直接 raise ASRProviderError，self._ws（已建立）从不 close → 句柄泄漏。

判定：fake_ws.send 抛 OSError，断言 fake_ws.close 被调用、self._ws 复位为 None。
当前代码：close 未调用（红）；修复后：except 内关闭已建立的 self._ws（绿）。无计时竞态。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.adapters.asr.funasr_server as funasr_mod
from app.core.exceptions import ASRProviderError


@pytest.mark.asyncio
async def test_start_stream_closes_ws_on_send_failure():
    """connect 成功但 send(init_msg) 失败：已建立的 WS 必须被关闭，不能泄漏。"""
    provider = funasr_mod.FunASRServerProvider()
    provider._ws_url = "ws://localhost:10096"

    fake_ws = AsyncMock()
    # connect 成功返回 fake_ws（self._ws 已建立），随后 send(init_msg) 失败
    fake_ws.send = AsyncMock(side_effect=OSError("send failed"))
    fake_ws.close = AsyncMock()

    with patch.object(funasr_mod.websockets, "connect",
                      new=AsyncMock(return_value=fake_ws)):
        with pytest.raises(ASRProviderError):
            await provider.start_stream(AsyncMock())

    fake_ws.close.assert_awaited_once()
    assert provider._ws is None
