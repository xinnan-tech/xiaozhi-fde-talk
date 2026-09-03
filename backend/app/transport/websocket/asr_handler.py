"""ASR 专用 WebSocket 处理器（访谈创建时的录音转写，无需 session）。

流程：
  ws 连接 → 用户按按钮开始录音 → MediaRecorder 推 WebM 音频帧
  → 本 handler 实时解码 + 送 FunASR 流式识别 → 实时推送 asr 文本给前端
  → 用户松手 / 超时 → 前端请求 /api/v1/interviews/extract 提取字段 → 自动填表

生命周期与 session 无关：连接即用，断开即释放。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.adapters.asr.audio_decode import WebMDecoder
from app.adapters.asr.factory import create_asr_provider
from app.core.exceptions import AuthError
from app.transport.base import extract_auth, token_from_subprotocols

logger = logging.getLogger(__name__)

# 单次录音最长时长（防止用户忘记松手）
_MAX_RECORDING_SECONDS = 60


class ASRHandler:
    """ASR 专用 WS handler（无 session 关联）。"""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._decoder: Optional[WebMDecoder] = None
        self._stream_provider = None
        self._feed_lock = asyncio.Lock()
        self._stopped = False
        self._max_timer: Optional[asyncio.Task] = None

    async def run(self) -> None:
        # 鉴权在 accept 之前，与 interview WS（handler.py）同一规则：token 只认
        # 子协议 bearer.<jwt>，缺失/无效直接拒绝握手（uvicorn 回 HTTP 403），
        # 未认证连接进不了 WS 层，也就建不起上游 ASR 流、起不了 WebM 解码器。
        token = token_from_subprotocols(self.ws.scope.get("subprotocols"))
        try:
            await extract_auth(token)
        except AuthError as e:
            # accept 之前 close = 拒绝握手：uvicorn 回 HTTP 403，浏览器 onclose code=1006。
            await self.ws.close()
            logger.info("ASR WS 握手被拒（鉴权失败）：%s", e)
            return
        try:
            await self.ws.accept(subprotocol="bearer." + token)
            await self._loop()
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("ASR WS handler 异常")
        finally:
            await self._cleanup()

    async def _loop(self) -> None:
        """接收二进制音频帧，解码后送 ASR 流。"""
        self._decoder = WebMDecoder()
        self._stream_provider = create_asr_provider()
        self._stream_provider.on_dead = self._on_provider_dead
        await self._stream_provider.start_stream(self._on_utterance)

        # 启动最长录音定时器（兜底，防止用户忘记停）
        self._max_timer = asyncio.create_task(self._max_duration_reached())

        while True:
            raw = await self.ws.receive()
            if raw["type"] == "websocket.disconnect":
                break
            if "bytes" not in raw:
                continue
            frame = raw["bytes"]
            if len(frame) > 64 * 1024:
                continue
            await self._on_audio(frame)

    async def _on_audio(self, frame: bytes) -> None:
        """解码音频帧并送 ASR。"""
        if self._stopped or self._stream_provider is None:
            return
        async with self._feed_lock:
            pcm = await asyncio.to_thread(self._decoder.feed, frame)
        if pcm and self._stream_provider is not None:
            try:
                await self._stream_provider.feed_stream(pcm)
            except Exception:  # noqa: BLE001
                pass

    async def _on_utterance(self, text: str, is_final: bool) -> None:
        """ASR 返回一句转写结果 → 推给前端。"""
        if not text or self._stopped:
            return
        try:
            await self.ws.send_json({
                "type": "asr",
                "text": text,
                "final": is_final,
            })
        except Exception:  # noqa: BLE001
            pass

    def _on_provider_dead(self) -> None:
        """ASR provider 断连通知（记录日志，不影响录音流程）。"""
        logger.warning("ASR provider 断连")

    async def _max_duration_reached(self) -> None:
        """60s 超时自动停止。"""
        await asyncio.sleep(_MAX_RECORDING_SECONDS)
        if not self._stopped:
            logger.info("ASR 录音达到最大时长 %ds，自动停止", _MAX_RECORDING_SECONDS)
            await self._send_stop()

    async def _send_stop(self) -> None:
        """通知前端录音停止（前端收到后主动关 WS）。"""
        self._stopped = True
        try:
            await self.ws.send_json({"type": "stopped"})
        except Exception:  # noqa: BLE001
            pass

    async def _cleanup(self) -> None:
        """释放资源。"""
        self._stopped = True
        if self._max_timer is not None:
            self._max_timer.cancel()
        if self._stream_provider is not None:
            try:
                await self._stream_provider.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream_provider = None
        logger.info("ASR handler 已清理")
