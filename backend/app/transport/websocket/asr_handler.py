"""ASR 专用 WebSocket 处理器（访谈创建时的录音转写，无需 session）。

流程：
  ws 连接 → 用户按按钮开始录音 → AudioWorklet 推裸 PCM 音频帧（int16 mono 16kHz）
  → 本 handler 直接转发给 FunASR 流式识别 → 实时推送 asr 文本给前端
  → 用户松手 / 超时 → 前端请求 /api/v1/interviews/extract 提取字段 → 自动填表

生命周期与 session 无关：连接即用，断开即释放。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

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
        self._stream_provider = None
        self._stopped = False
        self._max_timer: Optional[asyncio.Task] = None
        # TODO 后续：/ws/v1/asr 加 hello 协商（与 /ws/v1/interview 一样要
        # format/音频参数 检查）。当前用首帧 EBML magic 兜底旧前端缓存：
        # 检测到 WebM 头立即 close + 明确日志。
        self._format_checked = False

    async def run(self) -> None:
        # 鉴权在 accept 之前：token 只认子协议 bearer.<jwt>，校验失败即拒握。
        token = token_from_subprotocols(self.ws.scope.get("subprotocols"))
        try:
            await extract_auth(token)
        except AuthError as e:
            # accept 之前 close = 拒绝握手：uvicorn 回 HTTP 403，浏览器 onclose code=1006。
            peer = self.ws.scope.get("client")
            await self.ws.close()
            logger.info(
                "ASR WS 握手被拒（鉴权失败）：peer=%s 原因=%s",
                f"{peer[0]}:{peer[1]}" if peer else "?", e,
            )
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
        """接收二进制 PCM 帧（int16 mono 16kHz）→ 直接送 ASR 流。"""
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
            # 首帧 EBML magic 检测：旧前端缓存（曾走 MediaRecorder/WebM）
            # 发来的字节流以 0x1A 0x45 0xDF 0xA3 开头，会被当 PCM 解析得
            # 静音/乱码。检测到立即 close，让前端有明确反馈而不是 60s 后
            # 才看到 no_result。
            if not self._format_checked:
                self._format_checked = True
                if frame[:4] == b"\x1a\x45\xdf\xa3":
                    logger.warning(
                        "ASR 收到 WebM 字节流（疑似旧前端缓存），关闭连接请刷新"
                    )
                    try:
                        await self.ws.close(code=4400)
                    except Exception:  # noqa: BLE001
                        pass
                    self._stopped = True
                    return
            await self._on_audio(frame)

    async def _on_audio(self, frame: bytes) -> None:
        """喂入 PCM 帧 → ASR 流式识别。

        PCM 字节流无共享可变状态（与 WebM cluster 累积缓冲相对），无需 to_thread
        卸载解码。provider.feed_stream 自身保证并发安全。
        """
        # 局部捕获 provider 引用：check 与 feed_stream 之间 _cleanup 可能
        # 并发跑（_max_duration_reached 触发 _send_stop → _cleanup 设
        # _stream_provider = None），不存局部变量会 AttributeError 被
        # except pass 静默吞 → 最后一两帧 PCM 丢失、funasr 缺尾。
        provider = self._stream_provider
        if self._stopped or provider is None or not frame:
            return
        # s16 mono PCM 必须 2 字节对齐；奇数字节截断最后一字节避免 ASR 帧偏移。
        if len(frame) % 2:
            logger.warning(
                "ASR PCM 帧奇数字节：bytes=%d 已截断最后 1B（协议错乱？）",
                len(frame),
            )
            frame = frame[:-1]
            if not frame:
                return
        try:
            await provider.feed_stream(frame)
        except Exception as exc:  # noqa: BLE001
            # best-effort：丢帧可观测，CI 跑 e2e 看到这条 warning 能定位
            # provider 假活 / WS 关闭竞态。原 except: pass 把 ASR 死链
            # 静默拖 60s 才被 _max_duration_reached 兜底。
            logger.warning("ASR feed_stream 失败（丢 1 帧）：%r", exc)

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
