"""音频管线：WebM decode → 流式 ASR（协议无关）。

由 SessionRuntime 持有，listen:start 时初始化，TERMINATED 时销毁。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app.adapters.asr.audio_decode import WebMDecoder
from app.adapters.asr.factory import (
    create_asr_provider,
    is_stream_asr,
)
from app.adapters.asr.level_monitor import LevelMonitor, LevelReading

logger = logging.getLogger(__name__)

# 管线产出的整句回调：(文本, 是否最终文本, 起始采样) → Runtime 创建段 + 持久化 + 推 asr + 触发辅导
OnUtterance = Callable[[str, bool, int], Awaitable[None]]


class AudioPipeline:
    """协议无关的音频管线（仅流式路径）。

    链路：decode → 喂流式 ASR → partial/final 回调
    """

    def __init__(
        self,
        on_utterance: OnUtterance,
        on_dead: Optional[Callable[[], Awaitable[None]]] = None,
        on_overflow: Optional[Callable[[], Awaitable[None]]] = None,
        on_low_level: Optional[Callable[[LevelReading], Awaitable[None]]] = None,
    ) -> None:
        self._on_utterance = on_utterance
        self._on_dead = on_dead
        self._on_overflow = on_overflow
        self._on_low_level = on_low_level
        self._level_monitor = LevelMonitor()
        self._is_stream = is_stream_asr()
        # 解码器（listen:start 后创建）
        self.decoder: Optional[WebMDecoder] = None
        self._pcm_samples = 0
        # stream provider（每会话一个实例，各自 WS）
        self._stream_provider = None
        # 解码临界区串行：zombie 重连窗口里两条连接可能并发 feed 同一 pipeline，
        # 而 WebMDecoder 的 _buf/_header 是共享可变状态、非线程安全。to_thread 把
        # decode 丢进线程池，故须用 lock 保证同一时刻只有一个 decode，否则并发写入
        # 会让簇边界错位、丢簇或重发（幽灵转写）。
        self._feed_lock = asyncio.Lock()

    # ── 生命周期 ──────────────────────────────────────────────

    async def listen_start(self) -> None:
        """listen:start → 确保解码器 + 流式 ASR provider 就绪。

        每次开始监听都重置解码器：前端每次都重建 MediaRecorder 发一条带 EBML
        头的完整新流（首次 / 重连 / 暂停继续均如此），解码器回到初始态重新定位
        头。后端 runtime 重建（重启 / 寄存过期）后，前端 recorder 发的续流不含
        EBML 头 → 沿用上一条流的缓存头会永久解不出 PCM，故每次都 reset。
        provider 仅在缺失/已死时重建；存活则复用，不杀掉好的 ASR 连接。
        """
        if self.decoder is None:
            self.decoder = WebMDecoder()
        self.decoder.reset()
        self._level_monitor.reset()
        self._pcm_samples = 0
        provider_alive = self._stream_provider is not None and self._stream_provider.is_alive
        if not provider_alive:
            if self._stream_provider is not None:
                try:
                    await self._stream_provider.close()
                except Exception:  # noqa: BLE001
                    pass
                self._stream_provider = None
            self._stream_provider = create_asr_provider()
            self._stream_provider.on_dead = self._on_dead
            await self._stream_provider.start_stream(self._on_stream_utterance)
        logger.info("音频管线开始监听：stream=%s provider_alive=%s",
                    self._is_stream, provider_alive)

    async def feed(self, audio: bytes, audio_format: str = "opus") -> None:
        """喂一帧 WebM 或 PCM → 推送流式 ASR。

        解码临界区（_decode_only + 游标更新）须串行：见 _feed_lock 说明。
        feed_stream / overflow / low_level 回调放到锁外——前者 provider 自带
        send lock，后两者只通知、无需阻塞后续 decode。
        """
        if audio_format == "pcm_s16le":
            pcm_new = audio
            overflowed = False
            low = self._level_monitor.feed(pcm_new) if pcm_new else None
            if pcm_new:
                self._pcm_samples += len(pcm_new) // 2
            logger.info("收到 PCM 音频帧：pcm_bytes=%d", len(pcm_new))
        else:
            logger.info("收到 WebM 音频帧：bytes=%d", len(audio))
            async with self._feed_lock:
                pcm_new = await asyncio.to_thread(self._decode_only, audio)
                overflowed = (
                    self.decoder is not None
                    and getattr(self.decoder, "overflowed", False)
                )
                if overflowed:
                    self.decoder.overflowed = False
                low = None
                if pcm_new:
                    self._pcm_samples += len(pcm_new) // 2
                    low = self._level_monitor.feed(pcm_new)
            logger.info("WebM 音频帧解码完成：webm_bytes=%d pcm_bytes=%d",
                        len(audio), len(pcm_new))
        if overflowed and self._on_overflow is not None:
            await self._on_overflow()
        if low is not None and self._on_low_level is not None:
            await self._on_low_level(low)
        if pcm_new and self._stream_provider is not None:
            await self._stream_provider.feed_stream(pcm_new)

    async def flush(self) -> None:
        """listen:stop / end → 强制解码残留 + 通知 ASR 流结束。"""
        if self.decoder is None:
            return
        async with self._feed_lock:
            pcm_new = await asyncio.to_thread(self.decoder.feed, b"", True)
            if pcm_new:
                self._pcm_samples += len(pcm_new) // 2
        if pcm_new and self._stream_provider is not None:
            await self._stream_provider.feed_stream(pcm_new)
        if self._stream_provider is not None:
            await self._stream_provider.stop_stream()
            await self._stream_provider.close()
            self._stream_provider = None

    async def close(self) -> None:
        """释放流式 provider 资源。"""
        if self._stream_provider is not None:
            try:
                await self._stream_provider.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream_provider = None

    async def reset_provider(self) -> None:
        """拆除当前流式 provider（保留解码器）。重连时由 runtime.bind 调。

        旧 provider 的 WS 可能「假活」——连接仍开但 ASR 会话已卡死、不再出字——
        is_alive 区分不出。复用这样的 provider 会音频进得来却永远不出字。拆除后由
        listen_start 建全新的；解码器保留（MediaRecorder 是连续 WebM 流，重连不重发
        EBML 头，重建解码器会永久哑流）。force_close 立即关 WS，不等收尾，避免卡死
        的旧 provider 拖垮重连。
        """
        p = self._stream_provider
        self._stream_provider = None
        if p is None:
            return
        try:
            await p.force_close()
        except Exception:  # noqa: BLE001
            pass  # best-effort：拆除失败也不阻断重连（旧 provider 已解除引用）

    # ── 内部 ──────────────────────────────────────────────────

    def _decode_only(self, webm: bytes) -> bytes:
        if self.decoder is None:
            return b""
        return self.decoder.feed(webm)

    async def _on_stream_utterance(self, text: str, is_final: bool) -> None:
        """流式 ASR 返回文本时的回调（2pass 模式：标签判断句尾，is_final 恒为 True）。"""
        if not text:
            return
        logger.info("音频管线收到最终转写：text=%r samples=%d",
                    text, self._pcm_samples)
        await self._on_utterance(text, True, self._pcm_samples)
