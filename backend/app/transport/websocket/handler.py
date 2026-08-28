"""WS 消息路由 + 连接生命周期（薄适配器）。

连接层只做成帧 / 传输鉴权 / wire↔规范消息翻译 / 分发到 Runtime 入站 API。
业务管线、辅导引擎、状态机、出站缓冲在 services/sessions/。

铁律1：连接生命周期 ≠ 会话生命周期。WS 断开 → Runtime 寄存到存活窗口；
窗口内重连 → 复用同一 Runtime（管线+引擎不重置）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from structlog.contextvars import bind_contextvars

from app.core.exceptions import ASRProviderError, AuthError, IllegalTransitionError
from app.domain.auth import CurrentUser
from app.core.config_store import get_session_runtime_config
from app.core.constants import _WS_ERROR_KEY, WsMsgType
from app.core.i18n import Keys, t as i18n_t
from app.core.i18n.context import current_locale, force_locale
from app.core.i18n.negotiator import resolve_locale
from app.core.policies import get_policy
from app.domain.session import SessionStatus
from app.services.sessions.manager import ConcurrentLimitError, manager
from app.services.sessions.runtime import SessionRuntime, registry
from app.transport.base import extract_auth

logger = logging.getLogger(__name__)

# WS 协议版本：hello 回包回显，客户端可据此判断协议面变更
PROTOCOL_VERSION = 1


def _token_from_subprotocols(subprotocols: list[str]) -> Optional[str]:
    """从 Sec-WebSocket-Protocol 列表里挑出 bearer.<token>，无则 None。"""
    for sp in subprotocols or []:
        if sp.startswith("bearer."):
            return sp[len("bearer."):]
    return None


def _ws_upgrade_accept_language(scope: dict) -> Optional[str]:
    """从 ASGI scope.headers 提取 Accept-Language（首条匹配的 tag）。"""
    for k, v in scope.get("headers", []) or []:
        try:
            kd = k.decode("latin-1").lower() if isinstance(k, bytes) else str(k).lower()
        except Exception:  # noqa: BLE001
            continue
        if kd == "accept-language":
            try:
                vd = v.decode("latin-1") if isinstance(v, bytes) else str(v)
            except Exception:  # noqa: BLE001
                continue
            # parse_accept_language 接受整条 header；我们只想拿首条 tag
            for raw in vd.split(","):
                tag = raw.strip().split(";", 1)[0].strip()
                if tag and tag != "*":
                    return tag
    return None


def _resolve_hello_locale(hello: dict, scope: dict) -> str:
    """hello 帧携带的 locale → Accept-Language → 默认（en-US）。"""
    return resolve_locale(
        hello.get("locale"),
        _ws_upgrade_accept_language(scope),
    )


async def _fail(
    ws,
    state=None,
    *,
    code: str,
    i18n_key: Optional[str] = None,
    close_code: Optional[int] = None,
    **params,
) -> None:
    """Send a localized error frame; optionally close.

    Args:
        ws: WebSocket connection.
        state: optional SessionState. If provided, locale is read from
            `state.locale` (set at hello). If None, falls back to
            `current_locale()` — the contextvar set by I18nHTTPMiddleware /
            hello parsing.
        code: wire code (e.g. "bad_handshake", "asr_unavailable",
            "session_ended").
        i18n_key: explicit i18n key (overrides default lookup). Required when
            the wire code alone is ambiguous (e.g. "asr_unavailable" can be
            initial connect failure OR mid-session disconnect).
        close_code: if set, also close with this RFC6455 code.

    `state` is intentionally positional with `None` default rather than
    keyword-only: existing call sites that pass only `ws` continue to work;
    new sites with a state handle pass it positionally without breaking the
    old call sites.
    """
    if state is not None:
        locale = getattr(state, "locale", None) or current_locale()
    else:
        locale = current_locale()
    key = i18n_key or _WS_ERROR_KEY.get(code)
    msg = i18n_t(key, locale=locale, **params) if key else code
    payload = {
        "type": "error",
        "code": code,
        "i18n_key": key,
        "i18n_params": dict(params),
        "message": msg,
    }
    if close_code is not None:
        payload["close"] = close_code
    await ws.send_json(payload)
    if close_code is not None:
        # WebSocket close reason is byte-limited (123B per RFC6455). Slice by
        # bytes to avoid splitting a multibyte sequence; Starlette's
        # WebSocket.close(reason: str) requires a string — uvicorn forwards
        # to websockets.frames.Close.serialize() which calls .encode() on the
        # reason and would raise AttributeError if passed bytes.
        reason_bytes = (msg or code).encode("utf-8")[:123]
        reason_text = reason_bytes.decode("utf-8", errors="ignore")
        await ws.close(code=close_code, reason=reason_text)


class WSHandler:
    """一条 WS 连接 = 一次访谈会话的连接层句柄。只路由/IO，业务在 Runtime。"""

    def __init__(self, ws: WebSocket, session_id: str) -> None:
        self.ws = ws
        self.session_id = session_id
        self.runtime: Optional[SessionRuntime] = None
        # 发起端的身份（前端 sessionStorage client_id）。缺省每连接唯一 → 等同总是不同身份。
        self.client_id: Optional[str] = None
        self._user: Optional[CurrentUser] = None
        self._handshake_timeout_s: float = 5.0   # 等首条 hello 的超时（避免客户端建连后不发 hello 永久挂住）
        self._max_frame_bytes: int = 64 * 1024   # 单帧大小上限（text/bytes 任一 payload）

    # ---- IO 辅助 ----
    async def _send(self, obj: dict) -> None:
        await self.ws.send_json(obj)

    # ---- 生命周期 ----
    async def run(self) -> None:
        # 鉴权在 accept 之前：token 只认子协议 bearer.<jwt>，缺失/无效直接拒绝握手
        # （uvicorn 回 HTTP 403），未认证连接连 WS 层都进不来。不读消息体 token——
        # 收消息必须先完成握手，accept-then-auth 会给无凭证连接留存活窗口。
        token = _token_from_subprotocols(self.ws.scope.get("subprotocols"))
        try:
            self._user = await extract_auth(token)
        except AuthError as e:
            # accept 之前 close = 拒绝握手：uvicorn 回 HTTP 403，浏览器 onclose code=1006。
            # WS 关闭码此刻没有载体可发，故不传 code。显式 close 表达拒意，
            # 不依赖服务器对「未 accept 即返回」的兜底行为。
            await self.ws.close()
            logger.info("WS 握手被拒（鉴权失败）：session=%s 原因=%s", self.session_id, e)
            return
        await self.ws.accept(subprotocol="bearer." + token)
        try:
            if not await self._handshake():
                return
            bind_contextvars(session_id=self.session_id)
            await self._loop()
        except WebSocketDisconnect as e:
            logger.info("WebSocket 已断开：session=%s code=%s", self.session_id, getattr(e, "code", "?"))
        except ASRProviderError as e:
            # ASR 连接失败是运营/配置问题（服务未启动 / ws_url 错），非内部 bug：
            # 只打一行告警（不打 traceback），并把可操作的原因发回前端
            logger.warning("ASR 不可用：session=%s 原因=%s", self.session_id, e)
            # ASRProviderError = I18nError；str(e) 会渲染成 "i18n:asr.connect_fail{...}"
            # 这种内部调试串不能直接喂给 ws.asr.connect_fail 模板的 {reason}。
            # 取 params 里的 clean reason，缺失时再退回 str(e)。
            try:
                await _fail(self.ws, code="asr_unavailable",
                            i18n_key=Keys.WS_ASR_CONNECT_FAIL,
                            reason=e.params.get("reason", str(e)))
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            logger.exception("WebSocket 异常：session=%s 原因=%s", self.session_id, e)
            try:
                await _fail(self.ws, code="internal")
            except Exception:
                pass
        finally:
            await self._cleanup()

    async def _handshake(self) -> bool:
        """等首条 hello → 认领会话 → start/reconnect → bind Runtime → 回 hello。

        鉴权已在 run() 的 accept 之前完成（self._user 非空）。
        """
        try:
            first = await asyncio.wait_for(
                self.ws.receive_text(), timeout=self._handshake_timeout_s
            )
        except asyncio.TimeoutError:
            await _fail(self.ws, code="handshake_timeout", close_code=4408)
            return False
        except WebSocketDisconnect:
            return False
        try:
            msg = json.loads(first)
        except json.JSONDecodeError:
            await _fail(self.ws, code="bad_handshake",
                        i18n_key=Keys.WS_BAD_HANDSHAKE_JSON,
                        close_code=4000)
            return False
        if msg.get("type") != "hello":
            await _fail(self.ws, code="bad_handshake",
                        i18n_key=Keys.WS_BAD_HANDSHAKE_ORDER,
                        close_code=4000)
            return False

        state = await manager.get(self.session_id)
        if state is None or state.session.user_id != self._user.user_id:
            await _fail(self.ws, code="not_found", close_code=4404)
            return False

        # 在 hello 通过 → 业务校验 → manager.start 之前捕获 locale：start 之后
        # 后续 _fail 调用可读 state.locale；contextvar 同步设置使 run() 内 _fail
        # 路径也能拿到正确 locale（manager.start 抛 I18nError 时 state 未刷新）。
        state.locale = _resolve_hello_locale(msg, self.ws.scope)
        force_locale(state.locale)

        try:
            is_reconnect = state.status in (SessionStatus.IN_PROGRESS, SessionStatus.SUSPENDED)
            if is_reconnect:
                state = await manager.on_reconnect(self.session_id)
            else:
                state = await manager.start(self.session_id)
        except ConcurrentLimitError as e:
            limit = getattr(e, "params", {}).get("limit", 0)
            await _fail(self.ws, code="concurrent_limit",
                        i18n_key=Keys.WS_SESSION_CONCURRENT_LIMIT,
                        close_code=4409, limit=limit)
            return False
        except IllegalTransitionError:
            # 会话已是终态（ended）：start 的 ended→in_progress 转换非法。
            # 这是业务状态而非内部错误，须以 session_ended + 4406 告知前端。
            await _fail(self.ws, code="session_ended", close_code=4406)
            return False

        # 获取或复用 Runtime（存活窗口内重连复用同一管线+引擎）
        policy = get_policy("ws")
        # liveness 已过、runtime 正在 _expire 的 end() 中——拒绝重连。
        # 必须在 get_or_create 之前判断，否则 _parked/_active 均空会新建孤儿 runtime
        # 漏进 _active 且无人回收。语义是终态：runtime 正在销毁，重试无意义。
        if registry.is_terminating(self.session_id):
            await _fail(self.ws, code="session_ended", close_code=4406)
            return False
        # 同步 start/on_reconnect 后：state 已被刷新，保留刚解析出的 locale。
        if state.locale is None:
            state.locale = _resolve_hello_locale(msg, self.ws.scope)
            force_locale(state.locale)
        self.runtime = registry.get_or_create(self.session_id, state, policy)
        # 同步初始化（ConfigStore._cache + LLM 单例）—— ainit 幂等，重连场景 no-op
        self.runtime.ainit()
        self.client_id = msg.get("client_id") or uuid4().hex

        # 连接竞争：已有不同身份的 owner 在线 → 不 bind，发 connection.conflict 让本端
        # 决定是否接管。同身份（同标签刷新/断网重连，client_id 相同）不算竞争，走下方
        # 正常 bind 无缝复用 runtime。pending 期间不调 manager副作用已在 start/on_reconnect
        # 完成且对 IN_PROGRESS 幂等；pending 断连时 _cleanup 因 _send_fn != self._send 而 no-op。
        if (self.runtime._send_fn is not None
                and self.runtime._bound_client_id != self.client_id):
            await self._send({
                "type": "connection.conflict",
                "i18n_key": Keys.WS_CONNECTION_CONFLICT.value,
                "i18n_params": {},
                "message": i18n_t(Keys.WS_CONNECTION_CONFLICT, locale=state.locale),
            })
            logger.info("连接检测到已有 owner，进入待决（pending）：session=%s owner=%s new=%s",
                        self.session_id, self.runtime._bound_client_id, self.client_id)
            return True  # 进入 _loop 等 connection.takeover；未 bind

        # 先回 hello，再 bind（bind 会触发首算 coaching.update / 重连 snapshot replay）。
        # 顺序保证客户端先收到 hello（含 resume_from_seq），再收到 coaching（design：hello 后首算失败不影响连接）
        await self._send({
            "type": "hello",
            "session_id": self.session_id,
            "protocol_version": PROTOCOL_VERSION,
            "audio_params": msg.get("audio_params", {}),
            "resume_from_seq": self.runtime.seq.resume_from_seq,
        })
        if is_reconnect:
            logger.info(
                "WebSocket 重连接管已有会话：session=%s resume_from_seq=%d",
                self.session_id, self.runtime.seq.resume_from_seq,
            )
        else:
            logger.info("WebSocket 新建会话连接：session=%s", self.session_id)
        await self.runtime.bind(self._send, self.client_id, self._self_evict)
        return True

    async def _loop(self) -> None:
        while True:
            raw = await self.ws.receive()
            if raw["type"] == "websocket.disconnect":
                logger.info("WebSocket 收到断开帧：session=%s code=%s reason=%r",
                            self.session_id, raw.get("code"), raw.get("reason"))
                break
            # 单帧大小上限（text/bytes 任一 payload）
            payload = raw.get("bytes") or raw.get("text") or ""
            if len(payload) > self._max_frame_bytes:
                await _fail(self.ws, code="frame_too_large",
                            close_code=4410, max_kb=64)
                return
            if "text" in raw:
                try:
                    await self._dispatch(json.loads(raw["text"]))
                except json.JSONDecodeError:
                    await _fail(self.ws, code="bad_json", close_code=4411)
                    return
            elif "bytes" in raw:
                # 隔离单帧异常：解码/喂流偶发失败不能拖垮整条访谈连接
                try:
                    await self._on_audio(raw["bytes"])
                except Exception as e:  # noqa: BLE001
                    logger.warning("音频帧已丢弃：session=%s 原因=%s", self.session_id, e)
            if self.runtime is not None and getattr(self.runtime, "_send_dead", False):
                logger.warning("出站通道已标记失效，关闭 WebSocket：session=%s", self.session_id)
                break

    # ---- 消息路由 → Runtime 入站 API ----
    async def _dispatch(self, msg: dict) -> None:
        if self.runtime is None:
            return
        t = msg.get("type", "")
        # 接管确认：pending（尚未 bind）连接专属，须在 ownership 守卫之前放行
        if t == "connection.takeover":
            await self._on_takeover()
            return
        # ownership 守卫：非当前 owner（pending 待决 / 已被接管）的常规入站一律忽略，
        # 避免被踢的旧连接在 WS 关闭前的那一帧污染他人会话（幽灵转写同类竞态）。
        if self.runtime._send_fn != self._send:
            return
        if t == "listen":
            state = msg.get("state")
            if state == "start":
                await self.runtime.listen_start()
            elif state == "stop":
                await self.runtime.listen_stop()
            else:
                # 未知值（拼写错误等）忽略而非按 stop 处理，避免静默停麦
                logger.warning("listen.state 未知已忽略：%r session=%s", state, self.session_id)
        elif t == "coaching.skip":
            await self.runtime.skip(msg.get("id"))
        elif t == "coaching.ignore":
            await self.runtime.ignore(msg.get("id"))
        elif t == WsMsgType.SESSION_TOUCH:
            # 纯 keepalive：只重置 manager._last_activity_at，不碰 ASR/引擎/管线。
            # 用户主动暂停过麦时发 listen:start 会重启录制管线——专门一个无副作用帧
            # 让 keepAlive 按钮安全。
            manager.touch(self.session_id)
        elif t == "hello":
            pass
        else:
            logger.warning("忽略未知消息类型：%s session=%s", t, self.session_id)

    async def _on_audio(self, frame: bytes) -> None:
        """成帧：4 字节 seq + payload → Runtime.submit_audio。"""
        if self.runtime is None or len(frame) < 4:
            return
        # 非当前 owner（pending / 已被接管）的音频一律丢弃，不喂共享管线
        if self.runtime._send_fn != self._send:
            return
        seq = int.from_bytes(frame[:4], "big")
        await self.runtime.submit_audio(seq, frame[4:])

    async def _on_takeover(self) -> None:
        """pending 连接确认接管：踢旧 owner → 绑自己 → 回 hello 让前端开麦。

        只能由 pending（未 bind）连接走到（owner 的常规入站走不到这里：其
        _send_fn == self._send，_dispatch 在 ownership 守卫前已分流 takeover）。
        """
        rt = self.runtime
        if rt is None:
            return
        if rt._fsm.is_terminated:
            await _fail(self.ws, code="session_ended", close_code=4406)
            return
        # 旧 owner 可能在待决期间自行离开（runtime 已 unbind / 被 park）。重新取回：
        # 取消 park 的存活窗口定时器，并让寄存账目回到 _active，避免接管后无人回收。
        # 传 manager 现值而非 rt.state——待决期间用户可能 PATCH 过 base_info/goal。
        if rt._send_fn is None:
            fresh = await manager.get(self.session_id) or rt.state
            rt = registry.get_or_create(self.session_id, fresh, get_policy("ws"))
            rt.ainit()
            self.runtime = rt
        await rt.takeover(self._send, self.client_id, self._self_evict)
        logger.info("连接已接管会话：session=%s client=%s", self.session_id, self.client_id)
        # 接管成功 → 回 hello（含 resume_from_seq），前端据此开麦发 listen:start。
        # takeover 内部已 bind（推了 coaching snapshot），hello 随后到，前端正常开麦。
        await self._send({
            "type": "hello",
            "session_id": self.session_id,
            "protocol_version": PROTOCOL_VERSION,
            "audio_params": {},
            "resume_from_seq": rt.seq.resume_from_seq,
        })

    async def _self_evict(self, code: int = 4402, reason: str = "") -> None:
        """由 runtime 调用关闭本连接的 WS：被另一连接接管（4402）或会话结束（4406）。

        随后本 handler 的 _cleanup 会因 _send_fn != self._send（已是新 owner）而 no-op，
        不会拆绑新 owner 或寄存 runtime。
        """
        try:
            await self.ws.close(code=code, reason=reason)
        except Exception:  # noqa: BLE001
            pass

    async def _cleanup(self) -> None:
        if self.runtime is None:
            return
        # ownership：只有当前绑定的 handler 才能拆绑/寄存。过时 handler（已被重连的新连接
        # 取代）整体 no-op——其迟到 cleanup 不能踩坏新连接。_send 是 bound method，
        # 用 == 比较：同实例同方法相等，不同 handler 不等；_send_fn 为 None 时也不等。
        if self.runtime._send_fn != self._send:
            logger.info("清理跳过（已被更新的连接接管）：session=%s", self.session_id)
            return
        # 关闭 ASR 管线（与用户点「暂停」同等待遇），再解绑并寄存。
        # listen_stop 幂等：已 LIVE_PAUSED 时直接 no-op。
        await self.runtime.listen_stop()
        # 解绑（unbind 内部会复查 flush 窗口里的竞态）。未实际拆绑 = 已被新连接取代 → 不寄存。
        # 会话已结束的场景：REST end 的后台拆除会把 runtime 置 TERMINATED，park 对
        # TERMINATED 的 runtime 不寄存、直接 drop，这里无需特判。
        unbound = await self.runtime.unbind(self._send)
        if not unbound:
            return
        # liveness_window_s 与 grace_period_s 同走 config_store（运营可调，对称）
        settings = await get_session_runtime_config()
        # 再确认未被新连接抢绑：成功 unbind 后 _send_fn 应为 None；若已非 None，说明重连已
        # 接管这条 runtime，不能把它从 _active 寄存掉（get_session_runtime_config 也 await）。
        if self.runtime._send_fn is not None:
            logger.info("清理时跳过寄存（拆除过程中已被重连接管）：session=%s", self.session_id)
            return
        registry.park(
            self.session_id,
            self.runtime,
            ttl_s=settings["liveness_window_s"],
        )
        await manager.on_disconnect(self.session_id)
