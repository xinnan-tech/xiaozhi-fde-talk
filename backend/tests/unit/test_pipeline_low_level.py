"""管线低电平检测接线：decode 出的 PCM 喂 LevelMonitor，触发 on_low_level
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
    """decoder.feed 逐次返回的块：1s 目标电平『语音』+ 1s 静音交替。"""
    out = []
    for i in range(cycles):
        out.append(_pcm(speech_dbfs, 1.0, seed=100 + i))
        out.append(b"\x00" * 32000)
    return out


def _pipeline_with_chunks(chunks: list[bytes]) -> AudioPipeline:
    """decoder.feed 逐次吐出给定块、provider 为桩的管线。"""
    p = AudioPipeline(lambda *a: None, on_low_level=AsyncMock())
    dec = MagicMock()
    dec.overflowed = False
    it = iter(chunks)
    dec.feed = lambda _b: next(it)
    p.decoder = dec
    p._stream_provider = MagicMock()
    p._stream_provider.feed_stream = AsyncMock()
    return p


async def test_feed_low_level_fires_callback_once():
    p = _pipeline_with_chunks(_chunks(-55))
    for _ in range(60):          # 60 × 1s = 60s（30 轮语音+静音）
        await p.feed(b"webm")
    p._on_low_level.assert_awaited()
    assert p._on_low_level.await_count == 1


async def test_feed_normal_level_no_callback():
    p = _pipeline_with_chunks(_chunks(-20))
    for _ in range(60):
        await p.feed(b"webm")
    p._on_low_level.assert_not_awaited()


async def test_listen_start_rearms_monitor():
    p = _pipeline_with_chunks(_chunks(-55))
    for _ in range(60):
        await p.feed(b"webm")
    assert p._on_low_level.await_count == 1

    # listen_start 需要存活的 provider；桩一个（alive 则不重建）。
    # 监控重置后 decoder 的块序列也要换新的（旧迭代器已耗尽）。
    import app.services.sessions.pipeline as pl
    provider = MagicMock()
    provider.is_alive = True
    provider.start_stream = AsyncMock()
    pl.create_asr_provider = lambda: provider
    await p.listen_start()
    it = iter(_chunks(-55))
    p.decoder.feed = lambda _b: next(it)

    for _ in range(60):
        await p.feed(b"webm")
    assert p._on_low_level.await_count == 2
