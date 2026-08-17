from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.pipeline import AudioPipeline


async def test_listen_start_keeps_alive_provider():
    """存活的 provider 不重建：重连复用同一条 ASR 连接，不杀掉好的 WS。"""
    p = AudioPipeline(lambda *a: None)
    old = MagicMock()
    old.is_alive = True
    old.close = AsyncMock()
    p._stream_provider = old
    created = []
    import app.services.sessions.pipeline as pl
    pl.create_asr_provider = lambda: created.append(1) or MagicMock(
        start_stream=AsyncMock(), close=AsyncMock())
    await p.listen_start()
    assert p._stream_provider is old          # 没换
    old.close.assert_not_called()              # 没关旧的
    assert created == []                       # 没新建


async def test_listen_start_rebuilds_dead_provider():
    """已死（is_alive=False）的 provider 才重建：先关旧的再建新的。"""
    closed = []
    p = AudioPipeline(lambda *a: None)
    old = MagicMock()
    old.is_alive = False
    old.close = AsyncMock(side_effect=lambda: closed.append(True))
    p._stream_provider = old
    new = MagicMock()
    new.start_stream = AsyncMock()
    new.close = AsyncMock()
    import app.services.sessions.pipeline as pl
    pl.create_asr_provider = lambda: new
    await p.listen_start()
    assert closed == [True]          # 旧的先关
    assert p._stream_provider is new


async def test_listen_start_creates_decoder_on_first_call():
    """首次 listen_start：创建解码器 + provider。"""
    p = AudioPipeline(lambda *a: None)
    new = MagicMock()
    new.start_stream = AsyncMock()
    new.close = AsyncMock()
    import app.services.sessions.pipeline as pl
    pl.create_asr_provider = lambda: new
    await p.listen_start()
    assert p._stream_provider is new
    assert p.decoder is not None


async def test_listen_start_resets_decoder_each_time():
    """每次 listen_start 重置解码器：前端每次都重建 MediaRecorder 发带头的新流，
    解码器回到初始态重新定位头，不复用上一条流的残留缓冲。

    后端 runtime 重建（重启 / 寄存过期）后 decoder 是新的，但前端 recorder 发的
    续流不含 EBML 头 → 解码器缓存的头失效 → 永久解不出 PCM。每次 listen_start reset
    让 decoder 重新等新流的头。
    """
    p = AudioPipeline(lambda *a: None)
    new = MagicMock()
    new.is_alive = True
    new.start_stream = AsyncMock()
    new.close = AsyncMock()
    import app.services.sessions.pipeline as pl
    pl.create_asr_provider = lambda: new
    await p.listen_start()
    dec1 = p.decoder
    assert dec1 is not None
    dec1._header = b"stale"            # 模拟上一条流残留的状态
    dec1._buf.extend(b"residue")

    await p.listen_start()             # 重连 / 暂停继续
    assert p.decoder is dec1           # 实例复用（不重建）
    assert dec1._header is None        # 但状态已重置，等新流的头
    assert bytes(dec1._buf) == b""


async def test_reset_provider_closes_old_and_keeps_decoder():
    """reset_provider 拆除旧 provider（重连用），保留解码器（连续 WebM 流不重发头）。"""
    p = AudioPipeline(lambda *a: None)
    old = MagicMock()
    old.force_close = AsyncMock()
    p._stream_provider = old
    dec = MagicMock()
    p.decoder = dec

    await p.reset_provider()

    assert p._stream_provider is None
    old.force_close.assert_awaited_once()
    assert p.decoder is dec            # 解码器保留


async def test_reset_provider_noop_when_no_provider():
    """无 provider 时 reset_provider 不应抛（首次 bind 走到这里）。"""
    p = AudioPipeline(lambda *a: None)
    await p.reset_provider()
    assert p._stream_provider is None


async def test_concurrent_feeds_serialize_decode():
    """zombie 重连窗口里两条连接并发 feed 同一 pipeline：decode 必须串行。

    WebMDecoder 的 _buf/_header 是共享可变状态、非线程安全，而 feed 用 to_thread
    把 decode 丢进线程池——并发 feed 会让簇边界错位、丢簇或重发（幽灵转写）。
    _feed_lock 保证同一时刻只有一个 decode 在跑（max concurrency == 1）；无锁时会是 3。
    """
    p = AudioPipeline(lambda *a: None)
    p.decoder = MagicMock()
    p.decoder.overflowed = False
    p._stream_provider = MagicMock()
    p._stream_provider.feed_stream = AsyncMock()

    state = {"current": 0, "max": 0}
    guard = threading.Lock()

    def slow_decode(_webm):
        with guard:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.02)              # 放大并发窗口，确保无锁时一定重叠
        with guard:
            state["current"] -= 1
        return b""

    p._decode_only = slow_decode
    await asyncio.gather(p.feed(b"a"), p.feed(b"b"), p.feed(b"c"))
    assert state["max"] == 1          # 从不重叠；无锁会是 3
