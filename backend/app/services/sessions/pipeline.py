"""音频管线：裸 PCM → 流式 ASR（协议无关）。

由 SessionRuntime 持有，listen:start 时初始化，TERMINATED 时销毁。
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

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

    链路：feed PCM → LevelMonitor 监测 + 送 provider → partial/final 回调
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
        # 流式 provider（每会话一个实例，各自 WS）
        self._stream_provider = None
        self._pcm_samples = 0

    # ── 生命周期 ──────────────────────────────────────────────

    async def listen_start(self) -> None:
        """listen:start → 确保流式 ASR provider 就绪。

        provider 仅在缺失/已死时重建；存活则复用，不杀掉好的 ASR 连接。
        PCM 流无状态，不需要解码器重置。
        """
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
        self._level_monitor.reset()
        self._pcm_samples = 0
        logger.info("音频管线开始监听：stream=%s provider_alive=%s",
                    self._is_stream, provider_alive)

    async def feed(self, audio: bytes) -> None:
        """喂一帧 PCM → 监测电平 + 推送流式 ASR。

        PCM 字节流无共享可变状态（与 WebM cluster 累积缓冲相对），并发 feed 由
        provider.send_lock 自带，本管线无需额外的 feed 锁。
        """
        # 协议错乱 / 旧前端残留可能发奇数字节：截断会丢一字节、ASR 帧偏移。
        # s16 mono PCM 必须按 2 字节对齐，截断最后 1B 比喂错位数据给 ASR 安全。
        if audio and len(audio) % 2:
            logger.warning(
                "PCM 帧奇数字节：bytes=%d 已截断最后 1B（协议错乱？）",
                len(audio),
            )
            audio = audio[:-1]
        pcm_new = audio
        low = self._level_monitor.feed(pcm_new) if pcm_new else None
        if pcm_new:
            self._pcm_samples += len(pcm_new) // 2
        logger.debug("收到 PCM 音频帧：pcm_bytes=%d", len(pcm_new))
        if low is not None and self._on_low_level is not None:
            await self._on_low_level(low)
        if pcm_new and self._stream_provider is not None:
            await self._stream_provider.feed_stream(pcm_new)

    async def flush(self) -> None:
        """listen:stop / end → 通知 ASR 流结束 + 释放 provider。

        PCM 通路下无解码残留要 flush（之前 WebMDecoder 需要 force=True 刷尾簇）。
        直接 stop_stream 把当前积攒的尾句送 ASR 流式识别，再 close 释放。
        """
        if self._stream_provider is None:
            return
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
        """拆除当前流式 provider。重连时由 runtime.bind 调。

        旧 provider 的 WS 可能「假活」——连接仍开但 ASR 会话已卡死、不再出字——
        is_alive 区分不出。复用这样的 provider 会音频进得来却永远不出字。拆除后由
        listen_start 建全新的。PCM 流无状态，无需保留任何解码器状态。
        force_close 立即关 WS，不等收尾，避免卡死的旧 provider 拖垮重连。
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

    async def _on_stream_utterance(self, text: str, is_final: bool) -> None:
        """流式 ASR 返回文本时的回调（2pass 模式：标签判断句尾，is_final 恒为 True）。"""
        if not text:
            return
        await self._on_utterance(text, True, self._pcm_samples)
