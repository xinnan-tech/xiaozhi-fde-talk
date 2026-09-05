"""流式 Doubao（火山引擎）ASR Provider。

参考 xiaozhi-server core/providers/asr/doubao_stream.py 实现，
适配当前项目的 ASRProvider 接口（start_stream/feed_stream/stop_stream）。

协议细节：
  - WebSocket URL：wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
    （多语种模式：bigmodel_nostream）
  - 二进制帧格式：4 字节头 + 4 字节长度 + gzip 压缩 payload
  - 鉴权：API Key（X-Api-Key / X-Api-Resource-Id / X-Api-Request-Id）
  - 停止：发送 message_type_specific_flags=0x02 的空音频帧
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import uuid
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import websockets
from websockets.exceptions import InvalidStatus

from app.adapters.asr.base import ASRProvider
from app.core.config_store import get_config_store

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# WS URL：多语种模式 vs 普通模式
_WS_URL_NORMAL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
_WS_URL_MULTILANG = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

# message_type 取值
_MSG_TYPE_INIT = 0x01
_MSG_TYPE_AUDIO = 0x02
# message_type_specific_flags：bit1=last frame（发送空 PCM 触发服务端结束）
_FLAG_LAST_FRAME = 0x02

# 句尾静默 padding（ms），让 VAD 及时检测到句尾
_TAIL_SILENCE_MS = 200


class DoubaoStreamProvider(ASRProvider):
    """流式 Doubao ASR Provider。"""

    interface_type = "stream"


    def __init__(self) -> None:
        store = get_config_store()
        P = "asr.doubao_stream."
        self._api_key: str = store.get_sync(f"{P}api_key") or ""
        self._resource_id: str = store.get_sync(f"{P}resource_id", "volc.seedasr.sauc.duration")
        self._uid: str = store.get_sync(f"{P}uid", "streaming_asr_service")
        self._workflow: str = store.get_sync(
            f"{P}workflow",
            "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate",
        )
        self._result_type: str = store.get_sync(f"{P}result_type", "single")
        self._format: str = store.get_sync(f"{P}format", "pcm")
        self._codec: str = store.get_sync(f"{P}codec", "raw")
        self._sample_rate: int = int(store.get_sync(f"{P}sample_rate") or 16000)
        self._bits: int = int(store.get_sync(f"{P}bits") or 16)
        self._channel: int = int(store.get_sync(f"{P}channel") or 1)
        self._end_window_size: int = int(store.get_sync(f"{P}end_window_size") or 800)
        self._boosting_table: str = store.get_sync(f"{P}boosting_table_name", "")
        self._correct_table: str = store.get_sync(f"{P}correct_table_name", "")

        # 多语种模式：language 使用 Doubao 的默认值 zh-CN
        if str(store.get_sync(f"{P}enable_multilingual", "false")).lower() != "false":
            self._ws_url: str = _WS_URL_MULTILANG
            # Doubao 使用 zh-CN 作为默认语言（与 FunASR 的 zh 不同）
            self._language: Optional[str] = store.get_sync(f"{P}language") or "zh-CN"
        else:
            self._ws_url = _WS_URL_NORMAL
            self._language = None

        # 运行时状态
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_dead: bool = False
        self._recv_task: Optional[asyncio.Task] = None
        self._on_utterance: Optional[Callable[[str, bool], Awaitable[None]]] = None
        self._send_lock = asyncio.Lock()
        self._is_stopping = False
        self.on_dead: Optional[Callable[[], Awaitable[None]]] = None

    @property
    def is_alive(self) -> bool:
        """WS 已建立且未在停止中 → 可继续 feed。"""
        return self._ws is not None and not self._ws_dead and not self._is_stopping

    # ── 流式生命周期 ─────────────────────────────────────────

    async def start_stream(
        self, on_utterance: Callable[[str, bool], Awaitable[None]]
    ) -> None:
        """连接 Doubao ASR 服务端 WS，发送初始化请求。"""
        if not self._api_key:
            raise ValueError("Doubao ASR api_key 未配置")

        self._on_utterance = on_utterance
        self._is_stopping = False
        self._ws_dead = False

        headers = self._api_key_auth()
        try:
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers,
                max_size=100_000_000,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
            )
        except InvalidStatus as e:
            # websockets 库不展示响应体，需要自己拿到 status + body
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", "N/A") if resp else "N/A"
            body_bytes = getattr(resp, "body", b"") if resp else b""
            body_str = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
            logger.error("Doubao ASR HTTP %s 拒绝: body=%s", status, body_str)
            raise
        except Exception as e:
            logger.exception("Doubao ASR 连接失败: %s", e)
            raise

        # 发送初始化请求
        request_params = self._construct_request(str(uuid.uuid4()))
        try:
            payload_bytes = gzip.compress(str.encode(json.dumps(request_params)))
            req = bytearray(self._generate_header(message_type=_MSG_TYPE_INIT))
            req.extend(len(payload_bytes).to_bytes(4, "big"))
            req.extend(payload_bytes)
            await self._ws.send(req)

            # 等待初始化响应
            init_res = await self._ws.recv()
            result = await self._parse_response(init_res)
            if result is None:
                raise ValueError("ASR 初始化响应解析失败")
            payload = result.get("payload_msg", {})
            # 成功响应无 code 字段；只有失败才带 code 且不为 1000
            if isinstance(payload, dict) and payload.get("code") is not None and payload.get("code") != 1000:
                error_msg = payload.get("error") or str(payload)
                await self._ws.close()
                self._ws = None
                raise ValueError(f"ASR 服务初始化失败: code={payload.get('code')}, msg={error_msg}")
        except Exception as e:
            logger.error("Doubao ASR 初始化失败: %s", e)
            if self._ws:
                try:
                    await self._ws.close()
                except Exception:  # noqa: BLE001
                    pass
            self._ws = None
            raise

        logger.info("Doubao ASR 流已启动: %s", self._ws_url)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def feed_stream(self, pcm_bytes: bytes) -> None:
        """发送一帧 PCM 数据（gzip 压缩后发送）。"""
        if self._ws is None or self._ws_dead or self._is_stopping:
            raise ValueError("ASR 流已关闭或正在停止，无法 feed")
        async with self._send_lock:
            try:
                payload = gzip.compress(pcm_bytes)
                req = bytearray(self._generate_audio_header())
                req.extend(len(payload).to_bytes(4, "big"))
                req.extend(payload)
                await self._ws.send(req)
            except Exception as e:
                logger.error("Doubao ASR feed 失败: %s", e)
                raise

    async def stop_stream(self) -> None:
        """发送结束帧（空 PCM + last_frame flag），触发最终结果返回。"""
        self._is_stopping = True
        if self._ws is not None and not self._ws_dead:
            try:
                # 先发送一段静音 padding
                silence_bytes = b"\x00" * (self._sample_rate * 2 * _TAIL_SILENCE_MS // 1000)
                silence_payload = gzip.compress(silence_bytes)
                req = bytearray(self._generate_audio_header())
                req.extend(len(silence_payload).to_bytes(4, "big"))
                req.extend(silence_payload)
                await self._ws.send(req)
            except Exception:  # noqa: BLE001
                pass

            try:
                # 发送结束帧（message_type_specific_flags=0x02）
                empty_payload = gzip.compress(b"")
                req = bytearray(
                    self._generate_header(
                        message_type=_MSG_TYPE_AUDIO,
                        message_type_specific_flags=_FLAG_LAST_FRAME,
                    )
                )
                req.extend(len(empty_payload).to_bytes(4, "big"))
                req.extend(empty_payload)
                await self._ws.send(req)
                logger.debug("已发送 Doubao ASR 结束帧")
            except Exception:  # noqa: BLE001
                pass

        # 等待 recv_loop 收完最终结果
        if self._recv_task:
            try:
                await asyncio.wait_for(self._recv_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._recv_task.cancel()
        logger.info("Doubao ASR 流已停止")

    async def close(self) -> None:
        """关闭 WS 连接，释放资源。"""
        ws = self._ws
        await self.stop_stream()
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ws = None
        self._is_stopping = False
        self._ws_dead = False
        logger.info("Doubao ASR 流已关闭%s", "" if ws is not None else "（无连接）")

    async def force_close(self) -> None:
        """立即关闭，不等 stop_stream 的 5s recv drain。

        用于重连时拆除旧 provider：旧 WS 可能「假活」——仍开但会话卡死，
        等 stop_stream 的 wait_for(recv_task) 会卡满超时。直接关 WS 让
        recv_loop 立刻收到 ConnectionClosed 退出。
        """
        self._is_stopping = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
        self._ws_dead = True

    # ── 内部 ─────────────────────────────────────────────────

    async def _recv_loop(self) -> None:
        """后台任务：接收 ASR 服务端响应，触发 on_utterance 回调。"""
        try:
            while self._ws:
                response = await self._ws.recv()
                await self._parse_response(response)
        except websockets.ConnectionClosed:
            pass
        except Exception as e:  # noqa: BLE001
            logger.exception("Doubao ASR 接收循环异常: %s", e)
        finally:
            unexpected = not self._is_stopping
            self._ws_dead = True
            if unexpected:
                self._is_stopping = True
                logger.warning("Doubao ASR 连接已断开")
                if self.on_dead is not None:
                    try:
                        await self.on_dead()
                    except Exception:  # noqa: BLE001
                        logger.exception("on_dead 回调执行失败")

    async def _parse_response(self, response: bytes) -> Optional[dict]:
        """解析 Doubao ASR 服务端响应，触发 on_utterance。

        初始化检查时调用方只用返回值；recv_loop 中调用方不关心返回值。
        """
        try:
            result = self._parse_ws_frame(response)
            if result is None:
                return None
            payload = result.get("payload_msg", {})
        except Exception as e:
            logger.debug("Doubao ASR 响应解析跳过: %s", e)
            return None

        if not isinstance(payload, dict):
            return {"payload_msg": payload}

        # 错误码 1013 = 无有效语音，静默跳过
        if payload.get("code") == 1013:
            return result

        # 检查 result.text，统一用 definite=true 判断句尾
        asr_result = payload.get("result", {})
        utterances = asr_result.get("utterances", [])

        for utterance in utterances:
            if utterance.get("definite", False):
                current_text = utterance.get("text", "").strip()
                if current_text and self._on_utterance:
                    logger.debug("Doubao ASR 识别: %s", current_text)
                    await self._on_utterance(current_text, is_final=True)
                break

        return result

    # ── 协议工具 ─────────────────────────────────────────────

    def _api_key_auth(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

    def _construct_request(self, reqid: str) -> dict:
        req = {
            "user": {"uid": self._uid},
            "request": {
                "reqid": reqid,
                "model_name": "bigmodel",
                "workflow": self._workflow,
                "show_utterances": True,
                "result_type": self._result_type,
                "sequence": 1,
                "end_window_size": self._end_window_size,
                "corpus": {
                    "boosting_table_name": self._boosting_table,
                    "correct_table_name": self._correct_table,
                },
            },
            "audio": {
                "format": self._format,
                "codec": self._codec,
                "rate": self._sample_rate,
                "bits": self._bits,
                "channel": self._channel,
                "sample_rate": self._sample_rate,
            },
        }
        if self._language:
            req["audio"]["language"] = self._language
        return req

    def _generate_header(
        self,
        version: int = 0x01,
        message_type: int = 0x01,
        message_type_specific_flags: int = 0x00,
        serial_method: int = 0x01,
        compression_type: int = 0x01,
        reserved_data: int = 0x00,
        extension_header: bytes = b"",
    ) -> bytes:
        """构造 4 字节 WS 帧头。"""
        header = bytearray()
        header_size = int(len(extension_header) / 4) + 1
        header.append((version << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(reserved_data)
        header.extend(extension_header)
        return bytes(header)

    def _generate_audio_header(self) -> bytes:
        """音频帧头（message_type=0x02）。"""
        return self._generate_header(
            version=0x01,
            message_type=_MSG_TYPE_AUDIO,
            message_type_specific_flags=0x00,
            serial_method=0x01,
            compression_type=0x01,
        )

    def _parse_ws_frame(self, res: bytes) -> Optional[dict]:
        """解析 Doubao WS 二进制响应帧。"""
        if len(res) < 4:
            logger.error("响应数据长度不足: %d", len(res))
            return None

        header = res[:4]
        message_type = header[1] >> 4

        # 服务端错误响应（message_type=0x0F）
        if message_type == 0x0F:
            code = int.from_bytes(res[4:8], "big", signed=False)
            msg_length = int.from_bytes(res[8:12], "big", signed=False)
            error_msg = json.loads(res[12:].decode("utf-8"))
            return {"code": code, "msg_length": msg_length, "payload_msg": error_msg}

        # JSON 响应：4 字节头 + 4 字节序列号 + 4 字节长度 + JSON
        try:
            length = int.from_bytes(res[8:12], "big")
            if length > 0 and length <= len(res) - 12:
                json_data = res[12:12 + length].decode("utf-8")
            else:
                json_data = res[8:].decode("utf-8")
            return {"payload_msg": json.loads(json_data)}
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.debug("JSON 解析失败: %s", e)
            return None
