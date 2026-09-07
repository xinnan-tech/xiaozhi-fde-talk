"""管线低电平检测接线：feed 的 PCM 喂 LevelMonitor，触发 on_low_level
回调（每开麦周期至多一次）；listen_start 重置监控可再次触发。

喂入用『1s 小声语音 + 1s 数字静音』交替即可——本文件测接线（回调触发/重置），
动态门的判定行为在 test_level_monitor.py 覆盖（含真实底噪用例）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np

from app.services.sessions.pipeline import AudioPipeline


def _pcm(dbfs: float, seconds: float, seed: int = 7) -> bytes:
    n = int(16000 * seconds)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    x = np.clip(x / np.sqrt(np.mean(x * x)) * (10 ** (dbfs / 20)), -1, 1)
    return (x * 32767).astype(np.int16).tobytes()


def _chunks(speech_dbfs: float, cycles: int = 30) -> list[bytes]:
    """1s 目标电平『语音』+ 1s 静音交替（每块按 1s 给定电平的 PCM）。"""
    out = []
    for i in range(cycles):
        out.append(_pcm(speech_dbfs, 1.0, seed=100 + i))
        out.append(b"\x00" * 32000)
    return out


def _pipeline(on_low_level) -> AudioPipeline:
    """构造好带 mock provider 的管线：feed 直接入 LevelMonitor（无解码器中间层）。"""
    p = AudioPipeline(lambda *a: None, on_low_level=on_low_level)
    provider = MagicMock()
    provider.is_alive = True
    provider.feed_stream = AsyncMock()
    p._stream_provider = provider
    return p


async def test_feed_low_level_fires_callback_once():
    on_low = AsyncMock()
    p = _pipeline(on_low)
    for chunk in _chunks(-55):
        await p.feed(chunk)
    on_low.assert_awaited()
    assert on_low.await_count == 1


async def test_feed_normal_level_no_callback():
    on_low = AsyncMock()
    p = _pipeline(on_low)
    for chunk in _chunks(-20):
        await p.feed(chunk)
    on_low.assert_not_awaited()


async def test_listen_start_rearms_monitor():
    on_low = AsyncMock()
    p = _pipeline(on_low)
    for chunk in _chunks(-55):
        await p.feed(chunk)
    assert on_low.await_count == 1

    # listen_start：桩的 provider is_alive=True → 不重建；只 reset LevelMonitor。
    await p.listen_start()
    for chunk in _chunks(-55):
        await p.feed(chunk)
    assert on_low.await_count == 2
