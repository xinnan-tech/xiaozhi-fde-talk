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
        on_low_level: Optional[Callable[[LevelReading], Awaitable[None]]] = None,
        on_misaligned: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._on_utterance = on_utterance
        self._on_dead = on_dead
        self._on_low_level = on_low_level
        self._on_misaligned = on_misaligned
        self._level_monitor = LevelMonitor()
        self._is_stream = is_stream_asr()
        # 流式 provider（每会话一个实例，各自 WS）
        self._stream_provider = None
        self._pcm_samples = 0
        # 连续奇数字节帧计数：协议错乱（中间代理截断 / 前端 bug）下持续
        # 出现 odd-byte 帧，单次截断 1B 不会污染后续，但累计起来是协议层面
        # 异常——到阈值后通过 _on_misaligned 通知前端走 audio_format_unsupported
        # 错误帧提示刷新。偶数字节帧出现即重置，避免抖动期间误触发。
        self._misaligned_streak = 0

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
        self._misaligned_streak = 0
        logger.info("音频管线开始监听：stream=%s provider_alive=%s",
                    self._is_stream, provider_alive)

    async def feed(self, audio: bytes) -> None:
        """喂一帧 PCM → 监测电平 + 推送流式 ASR。

        PCM 字节流无共享可变状态（与 WebM cluster 累积缓冲相对），并发 feed 由
        provider.send_lock 自带，本管线无需额外的 feed 锁。
        """
        # 协议错乱 / 旧前端残留可能发奇数字节：截断 1B 比喂错位数据给 ASR 安全。
        # 连续 ≥3 次出现视为协议层异常——单次抖动不必打扰用户，持续出现说明
        # 中间代理截断 / 前端 bug / 网络层错位，靠 _on_misaligned 通知前端走
        # audio_format_unsupported 错误帧提示刷新。偶数字节帧立即清零计数。
        _MISALIGNED_THRESHOLD = 3
        if audio and len(audio) % 2:
            logger.warning(
                "PCM 帧奇数字节：bytes=%d 已截断最后 1B（协议错乱？）",
                len(audio),
            )
            audio = audio[:-1]
            # 仅在回调存在时累计 streak：_on_misaligned is None（单测/mock
            # 路径）时只打日志不计数，避免 streak 无界增长。
            if self._on_misaligned is not None:
                self._misaligned_streak += 1
                if self._misaligned_streak >= _MISALIGNED_THRESHOLD:
                    # fire-once：触发后清零，避免每帧重复打扰
                    self._misaligned_streak = 0
                    await self._on_misaligned()
        else:
            self._misaligned_streak = 0
        pcm_new = audio
        low = self._level_monitor.feed(pcm_new) if pcm_new else None
        if pcm_new:
            self._pcm_samples += len(pcm_new) // 2
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
