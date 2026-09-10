from __future__ import annotations

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


async def test_listen_start_creates_provider_only():
    """首次 listen_start：建 provider，无解码器概念（PCM 通路下管线无状态组件）。"""
    p = AudioPipeline(lambda *a: None)
    new = MagicMock()
    new.start_stream = AsyncMock()
    new.close = AsyncMock()
    import app.services.sessions.pipeline as pl
    pl.create_asr_provider = lambda: new
    await p.listen_start()
    assert p._stream_provider is new
    # PCM 通路下无 decoder 字段（前置 decoder 路径已删除）
    assert not hasattr(p, "decoder")


async def test_reset_provider_closes_old():
    """reset_provider 拆除旧 provider（重连用）。PCM 通路下不需要保留任何解码器状态。"""
    p = AudioPipeline(lambda *a: None)
    old = MagicMock()
    old.force_close = AsyncMock()
    p._stream_provider = old

    await p.reset_provider()

    assert p._stream_provider is None
    old.force_close.assert_awaited_once()


async def test_reset_provider_noop_when_no_provider():
    """无 provider 时 reset_provider 不应抛（首次 bind 走到这里）。"""
    p = AudioPipeline(lambda *a: None)
    await p.reset_provider()
    assert p._stream_provider is None
