"""流式 FunASR Server WS 客户端。

连接 FunASR 服务端 WS（wss://localhost:10096）：
  - start_stream(on_utterance) 初始化流，注册回调
  - feed_stream(pcm_bytes) 推送 PCM 帧（16k 单声道 int16）
  - stop_stream() / close() 结束流并释放资源
  - 异步非阻塞：WS 收包在后台任务，回调在主事件循环触发
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import websockets

from app.adapters.asr.base import ASRProvider
from app.core.config_store import get_config_store
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys

# Aliased: ASRProviderError = I18nError. Existing `raise ASRProviderError(...)` and
# `except ASRProviderError` (in services/diagnostics.py) keep working; the
# localized message comes from Keys.*.
ASRProviderError = I18nError

logger = logging.getLogger(__name__)

# 本地地址：连这些主机时强制不走系统代理（否则 ALL_PROXY=socks5 会让 websockets
# 去连 SOCKS 代理，而本地 FunASR 直连即可，且 python-socks 通常未装）
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# FunASR 2pass 句尾标签：有 <|...|> 的 text = 完整纠错句；热路径每消息都判，预编译
_TAG_RE = re.compile(r"<\|")
_STRIP_RE = re.compile(r"<\|[^|]*\|>")

# 句尾静音 padding：发 is_speaking=false 前先塞一段静音，
# 让 FunASR 内部 VAD 立刻检测到句尾并切句（避免等 30s 句尾超时）。
# 1000ms 给 VAD 留足识别窗口（部分服务 VAD 最短静音阈值 ≥600ms）。
_TAIL_SILENCE_MS = 1000

# FunASR `language` 字段合法值：zh | en | ja | ko | yue | auto。
# Admin UI 的 asr.language 下拉是 {zh, yue, en}（与 FunASR 合法集对齐）。
# 我们的 ENUM_KEYS 已经把选项限定到这三个 —— 映射层在 adapter 这里是 identity +
# 防御性 normalize（万一 DB 里漏进 ja/ko 等也能静默回退自动检测）。
_FUNASR_LANG_MAP: dict[str, str] = {
    "zh": "zh",
    "yue": "yue",
    "en": "en",
}


def _to_funasr_language(config_value: str | None) -> str:
    """asr.language 配置值 → FunASR init_msg.language；未识别回退空串（FunASR 自动检测）。"""
    return _FUNASR_LANG_MAP.get((config_value or "").strip().lower(), "")


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in _LOCAL_HOSTS


def _build_ssl_context(ws_url: str) -> ssl.SSLContext:
    """按目标地址构造 SSL context。

    优先级：asr.ws_verify_ssl=false → 跳过证书验证（适用于自签/过期证书）；
    否则本地自签 → 关验证；远程 → 完整验证。
    """
    ctx = ssl.create_default_context()
    # 用户显式关闭 SSL 验证
    if get_config_store().get_sync("asr.funasr_server.ws_verify_ssl") == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif _is_local(ws_url):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect_reason(exc: Exception) -> str:
    """把底层连接异常翻成面向用户的中文原因。

    websockets 对多地址（IPv6+IPv4）连接失败会聚合成一个 errno=None 的 OSError，
    因此不能只靠 isinstance/errno，还需看文本。
    """
    if isinstance(exc, asyncio.TimeoutError):  # TimeoutError / SSLError 均为 OSError 子类，需先判
        return "连接超时"
    if isinstance(exc, ssl.SSLError):
        return "TLS 握手失败（确认 wss/ws 协议与端口）"
    if isinstance(exc, (ConnectionError, OSError)):
        low = str(exc).lower()
        if "refused" in low or "connect call failed" in low:
            return "连接被拒绝（确认 ASR 服务已启动）"
        if "timed out" in low:
            return "连接超时"
        return "网络错误，无法连接 ASR 服务"
    if isinstance(exc, websockets.InvalidURI):
        return "ws_url 格式不正确"
    if isinstance(exc, websockets.InvalidStatus):
        return f"服务端返回异常状态（{exc}）"
    return f"{type(exc).__name__}: {exc}"


class FunASRServerProvider(ASRProvider):
    """流式 FunASR Server provider。每会话一个实例（各自的 WS 连接）。"""

    interface_type = "stream"

    def __init__(self) -> None:
        store = get_config_store()
        # 不再 or 兜底 localhost：DB 显式为空时 start_stream 抛 ASRProviderError，
        # prod 没配 ASR 第一次请求就报错（fail-fast），不再静默连 localhost 失败。
        P = "asr.funasr_server."
        self._ws_url = store.get_sync(f"{P}ws_url") or ""
        self._sample_rate = int(store.get_sync(f"{P}sample_rate") or 16000)
        self._funasr_language: str = _to_funasr_language(store.get_sync(f"{P}language"))
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        # 连接已不可用（recv_loop 结束）。只立标志不清 self._ws：句柄必须保留
        # 到 close() 真正关闭底层 TCP——先单独跑过 stop_stream 的调用方
        # （pipeline.flush）也依赖 close() 仍能找到这条连接。
        self._ws_dead: bool = False
        self._recv_task: Optional[asyncio.Task] = None
        self._on_utterance: Optional[Callable[[str, bool], Awaitable[None]]] = None
        self._send_lock = asyncio.Lock()
        self._is_stopping = False
        self.on_dead: Optional[Callable[[], Awaitable[None]]] = None
        self._session_id = "interview"

    @property
    def is_alive(self) -> bool:
        """WS 已建立且未在停止中 → 可继续 feed。recv_loop 结束会置 _ws_dead。"""
        return (self._ws is not None and not self._ws_dead
                and not self._is_stopping)

    # ── 流式生命周期 ─────────────────────────────────────────

    async def start_stream(
        self, on_utterance: Callable[[str, bool], Awaitable[None]]
    ) -> None:
        """连接 FunASR 服务端 WS（SSL + 自签名证书），初始化 2pass 会话。"""
        if not self._ws_url.strip():
            # 与同文件 ASR_DEAD / ASR_CONNECT_FAIL 同款 i18n 化错误，handler
            # 现有 except ASRProviderError 自动接住；前端拿 code + 502。
            # strip() 防 DB 写入全空白 / 误配空格字符串。
            raise ASRProviderError(Keys.ASR_URL_NOT_CONFIGURED, http_status=502)
        self._on_utterance = on_utterance
        ws_url = self._ws_url.rstrip("/")
        connect_kwargs = dict(
            ssl=_build_ssl_context(ws_url),
            max_size=100_000_000,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
        )
        # websockets.connect() 无 proxy kwarg，默认走系统解析器直连即可
        try:
            self._ws = await websockets.connect(ws_url, **connect_kwargs)
            self._ws_dead = False
            # xiaozhi-server 格式：2pass 模式（实时识别 + 句尾离线纠错）
            init_msg = {
                "mode": "2pass",
                "chunk_size": [5, 10, 5],
                "chunk_interval": 10,
                "wav_name": self._session_id,
                "is_speaking": True,
                "use_itn": True,
                "audio_fs": self._sample_rate,
            }
            if self._funasr_language:
                init_msg["language"] = self._funasr_language
            await self._ws.send(json.dumps(init_msg))
        except (OSError, asyncio.TimeoutError, ssl.SSLError, websockets.WebSocketException) as e:
            # connect 成功但 send(init_msg) 失败时，self._ws 已是建立好的连接——
            # 必须显式关闭释放句柄，否则泄漏一个底层 WS。
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ws = None
            # 连接失败属于运营/配置问题，翻成领域异常：handler 走"干净告警"分支，
            # 不打 traceback，并把真实原因（服务未启动 / ws_url 错 / TLS）告诉用户
            raise ASRProviderError(
                Keys.ASR_CONNECT_FAIL, http_status=502,
                ws_url=ws_url, reason=_connect_reason(e),
            ) from e
        logger.info("ASR 流已启动：%s", ws_url)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def feed_stream(self, pcm_bytes: bytes) -> None:
        if self._ws is None or self._ws_dead or self._is_stopping:
            raise ASRProviderError(Keys.ASR_DEAD, http_status=502)
        async with self._send_lock:
            try:
                await self._ws.send(pcm_bytes)
            except Exception as e:  # noqa: BLE001
                raise ASRProviderError(
                    Keys.ASR_FEED_FAIL, http_status=502, err=str(e),
                ) from e

    async def stop_stream(self) -> None:
        """通知 ASR 服务端音频发送完毕，触发最终结果返回。

        先发一段静音 PCM padding（_TAIL_SILENCE_MS）让 FunASR 内部 VAD
        立刻识别到句尾，再发 is_speaking=false 触发 2pass 离线纠错；
        否则末段连续语音会等满 30s 句尾超时。
        """
        self._is_stopping = True
        if self._ws is not None and not self._ws_dead:
            try:
                # 16k 单声道 int16 = 2 字节/采样；零值即静音
                silence_bytes = b"\x00" * (self._sample_rate * 2 * _TAIL_SILENCE_MS // 1000)
                await self._ws.send(silence_bytes)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._ws.send(json.dumps({"is_speaking": False}))
            except Exception:  # noqa: BLE001
                pass
        if self._recv_task:
            try:
                await asyncio.wait_for(self._recv_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._recv_task.cancel()
        logger.info("ASR 流已停止")

    async def close(self) -> None:
        """关闭 WS 连接，释放资源。

        无论此前是否单独跑过 stop_stream（pipeline.flush 的序列），这里都必须
        关掉底层 TCP。recv_loop 结束只置 _ws_dead、保留 self._ws 句柄，故此处
        先抓局部引用再 stop_stream 后仍能找到连接；真无连接（start_stream 未
        成功）则无事可做。
        """
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
        logger.info("ASR 流已关闭%s", "" if ws is not None else "（无连接）")

    async def force_close(self) -> None:
        """立即关闭，不等 stop_stream 的 5s recv drain。

        重连复用 runtime 时拆除旧 provider 用：旧 provider 的 WS 可能「假活」（仍开
        但 2pass 会话卡死、不再出字），等 stop_stream 的 wait_for(recv_task) 收尾会卡
        满超时。直接关 WS 让 recv_loop 立刻收到 ConnectionClosed 退出；_is_stopping=True
        使其 finally 视为预期关闭、不触发 on_dead（这是预期回收，非异常断连）。
        """
        self._is_stopping = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()

    # ── 内部 ─────────────────────────────────────────────────

    async def _recv_loop(self) -> None:
        try:
            while self._ws:
                response = await self._ws.recv()
                is_final = await self._parse_response(response)
                if is_final:
                    break
        except websockets.ConnectionClosed:
            pass
        except Exception as e:  # noqa: BLE001  (CancelledError is BaseException，不在此捕获)
            logger.exception("ASR 接收循环异常：%s", e)
        finally:
            unexpected = not self._is_stopping
            # 连接视为不可用，但不清 self._ws：close() 还需要这个句柄去关
            # 底层 TCP（recv 被 cancel 的 finally 里清句柄会让先单独跑过
            # stop_stream 的调用方永久漏掉这条连接）。
            self._ws_dead = True
            if unexpected:
                self._is_stopping = True
                logger.warning("ASR 接收循环结束：连接已断开")
                if self.on_dead is not None:
                    try:
                        await self.on_dead()
                    except Exception:  # noqa: BLE001
                        logger.exception("on_dead 回调执行失败")

    async def _parse_response(self, response: bytes | str) -> bool:
        """解析 FunASR 服务端响应，触发 on_utterance 回调。

        2pass 模式用标签判断句尾：有 <|...|> 标签的 text = 完整纠错句，
        否则为中间态忽略。is_final 参数不再依赖 FunASR 的 is_final 字段。
        """
        if self._on_utterance is None:
            return False

        try:
            if isinstance(response, bytes):
                response = response.decode("utf-8")
            msg = json.loads(response)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("FunASR 返回无法解析：type=%s", type(response).__name__)
            return False

        text = ""

        if isinstance(msg, dict):
            raw = msg.get("text", "").strip()
            logger.info("FunASR 返回：text=%r is_final=%r has_tag=%s",
                        raw, msg.get("is_final"), bool(_TAG_RE.search(raw)))
            # 有 <|...|> 标签 → 完整纠错句（2pass 句尾）；无标签 → 中间态，跳过
            if _TAG_RE.search(raw):
                text = _STRIP_RE.sub("", raw).strip()

        if text and self._on_utterance:
            logger.info("FunASR 输出最终文本：%r", text)
            await self._on_utterance(text, is_final=True)

        # FunASR 的 is_final 字段在 2pass 模式下不准确，忽略之
        return False
