"""FunASRMockProvider 契约测试。

Mock provider 用于 e2e/本地开发替代真 FunASR Server：
- 完全离线：不连 WS、不起端口、不开线程
- 每 ~0.5s 喂入的 PCM 触发一次 on_utterance("测试语音识别结果", True)
- 接口契约与 FunASRServerProvider 一致（is_alive / start / feed / stop / close / force_close）

TDD 红→绿：本文件先于 funasr_mock.py 落地。
"""
from __future__ import annotations

import asyncio

import pytest

from app.adapters.asr.funasr_mock import FunASRMockProvider


# 0.5s 16k 单声道 int16 = 16000 * 2 bytes = 32000 bytes。
# 实际 mock 阈值是 16000（user spec），单声道单字节近似，便于测试断言。
_HALF_SEC_PCM = b"\x00" * 16000


@pytest.mark.asyncio
async def test_module_imports():
    """契约：模块可导入、类名固定。"""
    from app.adapters.asr.funasr_mock import FunASRMockProvider as P
    assert P is FunASRMockProvider


def test_interface_type_is_stream():
    """契约：mock 是流式 provider。"""
    assert FunASRMockProvider.interface_type == "stream"


def test_is_alive_false_before_start():
    """未启动时 is_alive 为 False。"""
    p = FunASRMockProvider()
    assert p.is_alive is False


@pytest.mark.asyncio
async def test_start_stream_sets_alive():
    """start_stream 后 is_alive 为 True。"""
    p = FunASRMockProvider()
    cb = AsyncNoop()
    await p.start_stream(cb)
    try:
        assert p.is_alive is True
    finally:
        await p.close()


@pytest.mark.asyncio
async def test_feed_triggers_callback_after_threshold():
    """喂满 ~0.5s 静音 PCM 后回调触发，text="测试语音识别结果", is_final=True。"""
    p = FunASRMockProvider()
    captured: list[tuple[str, bool]] = []

    async def cb(text: str, is_final: bool) -> None:
        captured.append((text, is_final))
        evt.set()

    evt = asyncio.Event()
    await p.start_stream(cb)
    try:
        await p.feed_stream(_HALF_SEC_PCM)
        # 留些余量给后台 pump_loop 跑一帧
        await asyncio.wait_for(evt.wait(), timeout=2.0)
    finally:
        await p.close()

    assert len(captured) >= 1
    text, is_final = captured[0]
    assert text == "测试语音识别结果"
    assert is_final is True


@pytest.mark.asyncio
async def test_multiple_feeds_accumulate_callbacks():
    """多次喂入累计触发多次回调（每达阈值一次）。"""
    p = FunASRMockProvider()
    captured: list[str] = []

    async def cb(text: str, is_final: bool) -> None:
        captured.append(text)

    target = 3
    target_event = asyncio.Event()

    async def cb_with_signal(text: str, is_final: bool) -> None:
        captured.append(text)
        if len(captured) >= target:
            target_event.set()

    await p.start_stream(cb_with_signal)
    try:
        for _ in range(target):
            await p.feed_stream(_HALF_SEC_PCM)
        await asyncio.wait_for(target_event.wait(), timeout=3.0)
    finally:
        await p.close()

    assert len(captured) >= target


@pytest.mark.asyncio
async def test_stop_stream_flushes_remaining_buffer():
    """stop_stream 把残留 buffer flush 一次（即使不足阈值也出回调）。"""
    p = FunASRMockProvider()
    captured: list[str] = []

    flushed = asyncio.Event()

    async def cb(text: str, is_final: bool) -> None:
        captured.append(text)
        flushed.set()

    await p.start_stream(cb)
    # 喂一小段（不足阈值）
    await p.feed_stream(b"\x00" * 1000)
    # 立刻 stop —— 应触发一次 flush
    await p.stop_stream()

    # 等待回调
    await asyncio.wait_for(flushed.wait(), timeout=2.0)

    assert len(captured) >= 1
    assert captured[-1] == "测试语音识别结果"


@pytest.mark.asyncio
async def test_close_resets_alive():
    """close 后 is_alive 为 False。"""
    p = FunASRMockProvider()
    await p.start_stream(AsyncNoop())
    assert p.is_alive is True
    await p.close()
    assert p.is_alive is False


@pytest.mark.asyncio
async def test_force_close_returns_quickly():
    """force_close 立即关闭不挂起（不阻塞等回调）。"""
    p = FunASRMockProvider()

    async def slow_cb(text: str, is_final: bool) -> None:
        await asyncio.sleep(10)  # 永远不返回

    await p.start_stream(slow_cb)
    # 喂数据触发回调进入 sleep
    await p.feed_stream(_HALF_SEC_PCM)
    # 等一小会儿让回调被调用
    await asyncio.sleep(0.1)

    # force_close 应在合理时间内返回，不等 slow_cb 完成
    await asyncio.wait_for(p.force_close(), timeout=1.0)
    assert p.is_alive is False


# --- helpers ---


class AsyncNoop:
    """占位回调（协程签名）。start_stream 接受 Callable[[str,bool], Awaitable[None]]。"""

    async def __call__(self, text: str, is_final: bool) -> None:  # noqa: D401, ARG002
        return None
