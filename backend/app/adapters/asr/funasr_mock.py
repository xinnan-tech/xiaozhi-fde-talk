"""FunASR Mock provider（离线、纯 asyncio）。

为 e2e / 本地开发提供一个零依赖的 ASR 替代：
  - 不连 WS / 不起端口 / 不开线程
  - 每 ~0.5s 后台任务检查 buffer，达到阈值就触发 on_utterance(text, is_final=True)
  - 接口契约与 FunASRServerProvider 完全一致（is_alive / start / feed / stop / close / force_close）

切句节奏：buffer >= _CHUNK_BYTES (~16000 ≈ 0.5s 16k 单声道 int16) → 出一句。
短 buffer 在 stop_stream 时 flush 一次，避免最后一段遗失。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app.adapters.asr.base import ASRProvider

logger = logging.getLogger(__name__)

# 切句阈值：~0.5s 16k 单声道 int16 = 16000 * 2 = 32000 bytes。
# user spec 用 16000（视为 0.5s 单字节近似），测试按 16000 喂入对齐。
_CHUNK_BYTES = 16000

# mock 出的固定文本（与测试断言对齐）
_MOCK_TEXT = "测试语音识别结果"

# pump_loop 轮询间隔
_PUMP_INTERVAL_S = 0.1


class FunASRMockProvider(ASRProvider):
    """离线 mock 流式 ASR provider。"""

    interface_type = "stream"

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._pump_task: Optional[asyncio.Task] = None
        self._on_utterance: Optional[Callable[[str, bool], Awaitable[None]]] = None
        self._stopped: bool = True

    @property
    def is_alive(self) -> bool:
        return not self._stopped

    async def start_stream(
        self, on_utterance: Callable[[str, bool], Awaitable[None]]
    ) -> None:
        """注册回调 + 启动后台 pump 任务。"""
        self._on_utterance = on_utterance
        self._buffer = b""
        self._stopped = False
        self._pump_task = asyncio.create_task(self._pump_loop())
        logger.info("FunASRMock 流已启动")

    async def feed_stream(self, pcm: bytes) -> None:
        """累积 PCM 到 buffer；非阻塞。"""
        if self._stopped:
            # 与 funasr_server 同语义：流已关时喂数据应报错。但基类默认不抛，
            # 这里为了 e2e 容错静默丢弃（避免 mock 误用造成硬失败）。
            return
        self._buffer += pcm

    async def stop_stream(self) -> None:
        """flush 残留 buffer + cancel pump_task。"""
        self._flush_once()
        self._stopped = True
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("FunASRMock 流已停止")

    async def close(self) -> None:
        """清理状态 + 关 pump。"""
        await self.stop_stream()
        self._on_utterance = None
        self._buffer = b""
        logger.info("FunASRMock 已关闭")

    async def force_close(self) -> None:
        """立即关闭，不等回调 drain（cancel pump_task 即可）。"""
        self._stopped = True
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ── 内部 ─────────────────────────────────────────────────

    async def _pump_loop(self) -> None:
        """每 _PUMP_INTERVAL_S 检查一次 buffer，flush 所有达到阈值的 chunk。

        同步累积的多帧一次性 flush：避免一次喂入 N 帧只出 1 个 callback。
        每次 flush 仅消费 _CHUNK_BYTES（1 句），让 inner while 能循环出多个 callback。
        """
        try:
            while not self._stopped:
                while len(self._buffer) >= _CHUNK_BYTES:
                    self._flush_chunk()
                await asyncio.sleep(_PUMP_INTERVAL_S)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("FunASRMock pump_loop 异常")

    def _flush_chunk(self) -> None:
        """消费 1 个 _CHUNK_BYTES 出一句 callback（pump_loop 用）。

        只切走 1 句的字节量，剩余留给后续 flush（一次喂入 N 帧也能分段出）。
        """
        if self._on_utterance is None:
            return
        self._buffer = self._buffer[_CHUNK_BYTES:]
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._on_utterance(_MOCK_TEXT, True))
        except RuntimeError:
            # 无运行中的事件循环（理论不应发生），直接 await
            asyncio.create_task(self._on_utterance(_MOCK_TEXT, True))

    def _flush_once(self) -> None:
        """把残留 buffer 视为最后一句出（stop_stream 用，不足阈值也出）。

        同步路径：把回调 schedule 到事件循环（create_task），
        避免阻塞 stop_stream。
        """
        if not self._buffer or self._on_utterance is None:
            self._buffer = b""
            return
        self._buffer = b""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._on_utterance(_MOCK_TEXT, True))
        except RuntimeError:
            asyncio.create_task(self._on_utterance(_MOCK_TEXT, True))
