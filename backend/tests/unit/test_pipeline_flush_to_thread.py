"""· pipeline.flush 不阻塞事件循环。

C1: decoder.feed(b"", force=True) 同步触发 WebMDecoder O(n²) 全量重解码；
事件循环冻结数十至数百毫秒。验证 flush 走 to_thread 后主事件循环不被冻结。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.services.sessions.pipeline import AudioPipeline


class _SlowDecoder:
    """模拟 WebMDecoder.feed(b'', force=True) 的慢路径：50ms 阻塞。"""
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, bool]] = []

    def feed(self, webm: bytes, force: bool = False) -> bytes:
        self.calls.append((webm, force))
        time.sleep(0.05)  # 50ms 同步阻塞
        return b""


async def _noop_on_utterance(text: str, is_final: bool, start_sample: int) -> None:
    pass


@pytest.mark.asyncio
async def test_flush_runs_decoder_in_thread_not_loop():
    """flush 期间主事件循环可处理其他任务（验证 to_thread 而非同步阻塞）。

    判据：一个 ~5ms 的伴随任务，若 loop 在 flush（50ms）期间自由，它应在 flush
    完成前就结束；若 flush 同步阻塞 loop，它只能在 flush 之后才结束。
    """
    pipeline = AudioPipeline(on_utterance=_noop_on_utterance)
    pipeline.decoder = _SlowDecoder()
    pipeline._stream_provider = None  # 跳过 ASR 路径

    other_completed_at: list[float] = []

    async def _other_task():
        await asyncio.sleep(0.005)  # 5ms；只要 loop 自由就能很快完成
        other_completed_at.append(time.monotonic())

    other = asyncio.create_task(_other_task())
    await asyncio.sleep(0)  # yield 让 other 进入 sleep

    flush_start = time.monotonic()
    await pipeline.flush()
    flush_done = time.monotonic()

    await other
    assert other_completed_at, "伴随任务未完成"
    # to_thread：loop 自由 → 伴随任务(5ms) 在 flush(50ms) 期间完成 → 早于 flush_done
    # 同步阻塞：loop 冻结 50ms → 伴随任务只能在 flush 后完成 → 晚于 flush_done
    assert other_completed_at[0] < flush_done, (
        f"伴随任务在 flush 之后才完成（other@{other_completed_at[0]-flush_start:.3f}s "
        f"vs flush_done@{flush_done-flush_start:.3f}s）→ flush 阻塞了事件循环"
    )


@pytest.mark.asyncio
async def test_flush_invokes_decoder_with_force_true():
    """flush 必须把 force=True 传给 decoder.feed（语义保持）。"""
    pipeline = AudioPipeline(on_utterance=_noop_on_utterance)
    decoder = _SlowDecoder()
    pipeline.decoder = decoder
    pipeline._stream_provider = None

    await pipeline.flush()

    assert decoder.calls == [(b"", True)], f"应调一次 force=True 空帧，实得 {decoder.calls}"
