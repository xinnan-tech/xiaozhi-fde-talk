"""协议无关的会话运行时。

SessionRuntime 持有音频管线 + 辅导引擎 + 出站缓冲 + 子状态机 + seq 跟踪。
连接生命周期 ≠ 会话生命周期：协议断≠会话断；存活窗口内重连不重置管线。

入站 API（所有协议统一调用）：submit_audio / listen_start / listen_stop / end / skip / ignore。
出站经 BoundedOutboundBuffer 三分类（stateless/stateful/critical）。

RuntimeRegistry 在存活窗口内寄存 Runtime，使断连重连复用同一管线+引擎。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from app.adapters.asr.level_monitor import LevelReading
from app.core.i18n import Keys, t as i18n_t
from app.core.outbound_send import safe_send
from app.core.policies import SessionPolicy, get_policy
from app.core.security import redact_text
from app.domain.session import Session, SessionStatus, TranscriptSegment
from app.persistence.repositories.interview import interview_repo
from app.services.coaching.engine import CoachingEngine
from app.services.sessions.outbound import BoundedOutboundBuffer
from app.services.sessions.pipeline import AudioPipeline
from app.services.sessions.seq import SeqTracker
from app.services.sessions.state import SessionState
from app.services.sessions.state_machine import (
    RuntimeState,
    RuntimeStateMachine,
)

logger = logging.getLogger(__name__)


def _touch(session_id: str) -> None:
    """更新会话活跃度。延迟导入 manager 以规避与 manager.py 的循环依赖。"""
    from app.services.sessions.manager import manager
    manager.touch(session_id)


# 出站回调：(msg_dict) → None（由 transport 层注入，如 ws.send_json）
SendFn = Callable[[dict], Awaitable[None]]


class SessionRuntime:
    """协议无关的会话运行时。持有管线 + 出站缓冲 + 状态机 + 辅导引擎。"""

    def __init__(
        self,
        state: SessionState,
        policy: Optional[SessionPolicy] = None,
    ) -> None:
        self.state = state
        self.policy = policy or get_policy("ws")
        self.seq = SeqTracker(state.session.consumed_seq)
        self._fsm = RuntimeStateMachine(RuntimeState.LIVE_PAUSED)
        self.outbound = BoundedOutboundBuffer(
            self.policy.outbound_buffer_size, self.policy.outbound_buffer_ttl_s
        )
        self._send_fn: Optional[SendFn] = None
        self._send_lock = asyncio.Lock()
        # owner 身份（前端 sessionStorage client_id）+ 被踢时关其 WS 的回调。
        # 连接竞争按 client_id 判定：同身份=同一端的刷新/断网重连（无缝复用），
        # 不同身份=另一端接管（takeover 踢旧 owner）。
        self._bound_client_id: Optional[str] = None
        self._evict_fn: Optional[Callable[..., Awaitable[None]]] = None
        self.engine = CoachingEngine(state, self._send)
        self.engine._persist = self._persist_for_recompute
        self.pipeline = AudioPipeline(
            self._on_utterance, on_dead=self._on_asr_dead, on_overflow=self._on_audio_overflow,
            on_low_level=self._on_low_level,
        )
        self._utterance_lock = asyncio.Lock()
        self._first_computed = False
        self._send_dead = False
        self._asr_dead = False
        self._dirty_segments = 0
        self._flush_interval_s = 5.0       # 去抖落盘窗口
        self._flush_dirty_segments = 5     # 脏段达此值立即落盘（双触发）
        self._flush_task: asyncio.Task | None = None

    def ainit(self) -> None:
        """同步初始化辅导引擎（ConfigStore._cache + LLM 单例）。

        RuntimeRegistry.get_or_create 在创建 Runtime 后调一次。bind() 之前完成。
        B 类配置已走同步 _cache，方法本身无需 await（保留 async 名字仅为 API 兼容）。
        """
        self.engine.ainit()

    # ── 连接绑定 ──────────────────────────────────────────────

    async def bind(self, send: SendFn, client_id: Optional[str] = None,
                   evict_fn: Optional[Callable[..., Awaitable[None]]] = None) -> None:
        """绑定连接：注入出站回调 + owner 身份，重推 critical + snapshot，恢复子状态。

        client_id 标识发起连接的客户端（前端 sessionStorage，每标签/每设备唯一）。
        同身份覆盖仍存活的 send_fn 属异常（旧 handler 未及 unbind 的 zombie 竞态）→ 告警；
        不同身份的覆盖只应发生在 takeover() 路径（已先踢人），这里仅兜底记 info。
        """
        await self._bind_core(send, client_id, evict_fn)

    async def _bind_core(self, send: SendFn, client_id: Optional[str],
                         evict_fn: Optional[Callable[..., Awaitable[None]]]) -> None:
        if self._send_fn is not None:
            if client_id is not None and self._bound_client_id == client_id:
                logger.warning(
                    "运行时 bind 覆盖了同身份仍存活的 send_fn（疑似 zombie）：session=%s client=%s",
                    self.state.session.id, client_id,
                )
            else:
                logger.info(
                    "运行时连接被接管：session=%s old_client=%s new_client=%s",
                    self.state.session.id, self._bound_client_id, client_id,
                )
        self._send_dead = False
        self._send_fn = send
        self._bound_client_id = client_id
        self._evict_fn = evict_fn
        self.engine.on_bind()
        # 重连时 replay critical 事件
        for msg in self.outbound.critical_for_replay():
            await self._raw_send(msg)
        if not self._first_computed:
            await self.engine.first_compute()
            self._first_computed = True
        else:
            # 重连：推一次当前清单 snapshot（不重跑首算）
            await self.engine.resend_current()
        # 新连接接管：遗留的 LIVE（旧 handler 未及 unbind 的 zombie 竞态）或
        # suspended_local（正常断连寄存）一律回到 live_paused（已连接、待 listen:start）。
        # 否则遗留 LIVE 会让 listen_start 幂等早退、ASR 管线不重建 → 重连后音频进得来
        # 却永远不出字。同时拆除旧 ASR provider：其 WS 可能假活（仍开但会话卡死、不再
        # 出字），is_alive 区分不出，复用会带病上岗；listen_start 会建全新的。
        # 解码器保留（连续 WebM 流不重发 EBML 头）。
        if self._fsm.state in (RuntimeState.LIVE, RuntimeState.SUSPENDED_LOCAL):
            self._fsm.transition(RuntimeState.LIVE_PAUSED)
            await self.pipeline.reset_provider()
        if self._fsm.state != RuntimeState.LIVE_PAUSED:
            logger.warning(
                "运行时 bind 后状态异常：session=%s state=%s（期望 live_paused）",
                self.state.session.id, self._fsm.state.value,
            )
        logger.info("运行时已绑定连接：session=%s state=%s client=%s",
                    self.state.session.id, self._fsm.state.value, client_id)

    async def takeover(self, send: SendFn, client_id: str,
                       evict_fn: Callable[..., Awaitable[None]],
                       reason: str = "连接已被另一个客户端接管") -> None:
        """踢旧 owner 后绑新 owner（不同身份连接竞争接管）。

        顺序严格：① 给旧 owner 发 connection.kicked（其仍在 receive，能收到）→
        ② _bind_core 绑新 owner（覆盖 _send_fn）→ ③ 调旧 owner 的 evict_fn 关其 WS。
        ② 先于③：旧 owner 随后的 _cleanup 看到 _send_fn 已是新 owner 的 send →
        ownership 不符 → 整体 no-op，不会把会话误转 suspended / 寄存掉。
        若此刻 _send_fn 已空（旧 owner 待决期间自行离开），跳过踢人、直接绑新。
        """
        old_evict = self._evict_fn
        old_client_id = self._bound_client_id
        should_kick = self._send_fn is not None and old_client_id != client_id
        if should_kick:
            try:
                await self._raw_send({
                    "type": "connection.kicked",
                    "reason": i18n_t(Keys.WS_CONNECTION_KICKED,
                                     locale=self.state.locale),
                    "i18n_key": Keys.WS_CONNECTION_KICKED.value,
                    "i18n_params": {},
                })
            except Exception:  # noqa: BLE001
                pass
        await self._bind_core(send, client_id, evict_fn)
        if should_kick and old_evict is not None:
            try:
                await old_evict()
            except Exception:  # noqa: BLE001
                pass

    async def unbind(self, send: Optional[SendFn] = None) -> bool:
        """解除连接绑定：强制落盘 + engine.on_unbind + null _send_fn + 转 SUSPENDED_LOCAL（管线/引擎保留）。

        ownership：只有当前绑定的 handler（_send_fn == send）才能拆绑。过时 handler（已被
        新连接取代）的 unbind 整体 no-op，避免 zombie cleanup 踩坏新连接的 _send_fn / FSM。
        send=None 表示内部/无条件调用（向后兼容）。_send 是 bound method，故用 == 而非 is。

        返回 True 表示本次确实拆绑（调用方据此决定是否 park）；False 表示因 stale/superseded
        未动。注意 _force_flush 会 await——其间新 handler 可能 bind 覆盖 _send_fn，故 flush 后
        必须复查 ownership，否则会 null 掉新 handler 的 _send_fn（check-then-await-then-act 漏洞）。
        """
        if send is not None and self._send_fn is not None and self._send_fn != send:
            logger.info("运行时 unbind 跳过（过时 handler）：session=%s state=%s",
                        self.state.session.id, self._fsm.state.value)
            return False
        if self._fsm.is_terminated or self._fsm.is_suspended:
            return False
        await self._force_flush()
        # 复查：flush 的 await 窗口里新 handler 可能已 bind（_send_fn 已变）。
        # 此时不再是 owner，整体 no-op——不能 null、不能转 suspended。
        if send is not None and self._send_fn is not None and self._send_fn != send:
            logger.info("运行时 unbind 中止（flush 期间已被新连接接管）：session=%s state=%s",
                        self.state.session.id, self._fsm.state.value)
            return False
        self.engine.on_unbind()
        self._send_fn = None
        self._bound_client_id = None
        self._evict_fn = None
        self._fsm.transition(RuntimeState.SUSPENDED_LOCAL)
        logger.info("运行时已解绑连接：session=%s → suspended_local", self.state.session.id)
        return True

    # ── 入站 API（所有协议统一调用）──────────────────────────

    async def submit_audio(self, session_seq: int, payload: bytes) -> None:
        """入站音频帧：seq 去重 → 喂管线（仅 LIVE 态处理）。"""
        if not self.seq.should_accept(session_seq):
            return
        self.seq.mark_consumed(session_seq)
        self.state.session.consumed_seq = self.seq.consumed_seq
        if not self._fsm.is_listening or self._asr_dead:
            return
        await self.pipeline.feed(payload)
        _touch(self.state.session.id)

    async def listen_start(self) -> None:
        """listen:start → LIVE：初始化管线 + 恢复辅导计时器。

        幂等：已 LIVE 且管线健康（_asr_dead=False）时直接返回。但若 _asr_dead（旧 ASR
        连接已死），即便 LIVE 也强制重建管线——重连复用 runtime 时旧管线可能已死，
        不重建会永远不出字。
        """
        # 重置 seq tracker：每次开麦都从头开始，前端 MediaRecorder 每次重建 seq 都从 0 编起。
        # 如果不重置，之前残留的 consumed_seq 会导致所有新帧被去重丢弃（前端 seq < consumed_seq）。
        self.seq = SeqTracker(0)
        self.state.session.consumed_seq = 0
        if self._fsm.is_listening and not self._asr_dead:
            return
        if not self._fsm.is_listening:
            self._fsm.transition(RuntimeState.LIVE)
        await self.pipeline.listen_start()
        self._asr_dead = False  # 新 provider 已建，清除历史 ASR 死亡标记
        self.engine.on_listen_resume()
        _touch(self.state.session.id)

    async def listen_stop(self) -> None:
        """listen:stop → LIVE_PAUSED：flush 管线（尾句入账）+ 收尾重算 + 强制落盘。"""
        if self._fsm.state != RuntimeState.LIVE:
            return
        self._fsm.transition(RuntimeState.LIVE_PAUSED)
        self.engine.on_listen_pause()
        await self.pipeline.flush()
        # flush 的 drain（stop_stream 垫静音触发 2pass 尾句纠错）完成后，
        # 尾句已进 transcript——此时若窗口非空补一次重算再进入暂停态
        self.engine.on_listen_stopped()
        await self._force_flush()
        _touch(self.state.session.id)

    async def end(self) -> None:
        """end → TERMINATED：flush 管线 + 强制落盘 + 辅导收尾 + 释放资源。"""
        await self._teardown(final_recompute=True)
        # final 清单推送完毕后，通知在线 owner 并关闭其连接。标准前端在 REST end
        # 成功后自行关 WS，这里兜底其余客户端——否则连接会一直挂到 idle 超时。
        if self._send_fn is not None:
            try:
                await self._send({"type": "session.ended", "session_id": self.state.session.id})
            except Exception:  # noqa: BLE001
                pass
        if self._evict_fn is not None:
            try:
                await self._evict_fn(4406, i18n_t(Keys.WS_CLOSE_SESSION_ENDED,
                                                 locale=self.state.locale))
            except Exception:  # noqa: BLE001
                pass

    async def suspend(self) -> None:
        """idle 挂起 → TERMINATED：flush 落盘 + 释放资源，会话仍可继续。

        与 end() 的区别：不做辅导终局重算（engine.on_end 的 final 推送），
        通知语义是「已挂起」而非「已结束」——DB 落 suspended，前端收到
        session.suspended 后停麦停重连，回列表可重新进入。若沿用 end()，
        前端会按 session.ended + 4406 进入只读态，与可继续的 suspended 矛盾。
        """
        await self._teardown(final_recompute=False)
        if self._send_fn is not None:
            try:
                await self._send({"type": "session.suspended", "session_id": self.state.session.id})
            except Exception:  # noqa: BLE001
                pass
        if self._evict_fn is not None:
            try:
                await self._evict_fn(4403, i18n_t(Keys.WS_CLOSE_SUSPENDED,
                                                 locale=self.state.locale))
            except Exception:  # noqa: BLE001
                pass

    async def push_report_ready(self, status: str) -> None:
        """推 report.ready 帧给当前在线 owner（若有）。

        由报告路由 get_or_generate 完成后回调触发：status ∈ {"ready", "failed"}。
        无存活连接（_send_fn is None，runtime 已 unbind/drop）时静默 no-op——前端
        拿不到推送但 GET 同步返回中已带 status，本身就能知道结果。
        走 self._send：进 critical 缓冲，重连时 replay（前端断线期间请求过报告也能收到）。
        """
        if self._send_fn is None:
            return
        try:
            await self._send({
                "type": "report.ready",
                "session_id": self.state.session.id,
                "status": status,
            })
        except Exception:  # noqa: BLE001
            logger.warning("report.ready 推送失败：session=%s", self.state.session.id)

    async def _teardown(self, *, final_recompute: bool) -> None:
        """end / suspend 共用的资源拆除：TERMINATED + flush + 落盘 + 关管线。"""
        if not self._fsm.is_terminated:
            self._fsm.transition(RuntimeState.TERMINATED)
        try:
            await self.pipeline.flush()
        except Exception:  # noqa: BLE001
            logger.warning("拆除时管线 flush 失败，继续：session=%s", self.state.session.id)
        await self._force_flush()
        if final_recompute:
            await self.engine.on_end()
        await self.pipeline.close()
        self.outbound.clear()
        _touch(self.state.session.id)

    async def shutdown_quick(self) -> None:
        """进程关停：释放 ASR + 落盘为已暂停（可继续），不等 LLM（区别于 end）。

        WS 随进程死亡，会话不再 live——落盘 suspended 让重启后语义一致、可重新进入。
        不写 ended：用户没主动结束，仍应能继续访谈。
        """
        try:
            await self.pipeline.close()
        except Exception:  # noqa: BLE001
            pass
        if self.state.session.status in (SessionStatus.SETTING_UP, SessionStatus.IN_PROGRESS):
            self.state.session.status = SessionStatus.SUSPENDED
        try:
            await self._save_state()
        except Exception:  # noqa: BLE001
            pass

    async def skip(self, item_id: Optional[str]) -> None:
        if item_id:
            self.state.skipped_ids.add(item_id)
            await self._save_state()
        _touch(self.state.session.id)

    async def ignore(self, item_id: Optional[str]) -> None:
        if item_id:
            self.state.ignored_ids.add(item_id)
            await self._save_state()
        _touch(self.state.session.id)

    # ── 内部 ──────────────────────────────────────────────────

    async def _on_asr_dead(self) -> None:
        if self._asr_dead:
            return
        self._asr_dead = True
        await self._send({
            "type": "error",
            "code": "asr_unavailable",
            "i18n_key": Keys.WS_ASR_DISCONNECTED.value,
            "i18n_params": {},
            "message": i18n_t(Keys.WS_ASR_DISCONNECTED, locale=self.state.locale),
        })
        logger.warning("ASR 连接已标记失效：session=%s", self.state.session.id)

    async def _on_audio_overflow(self) -> None:
        """解码缓冲触顶（长会话累积）。解码器已自动恢复到缓存的 EBML 头继续解码，
        仅丢触发那一帧（毫秒级），转写不中断——故只记日志，不打 error 帧。
        （打 error 会让前端置 errorShown=true，从而抑制后续断线的自动重连。）"""
        logger.info("解码缓冲溢出，已自动恢复：session=%s", self.state.session.id)

    async def _on_low_level(self, reading: LevelReading) -> None:
        """开麦周期内解码 PCM 电平持续过低（窗口读数 reading）：提示用户。

        触发条件见 LevelMonitor（p95 < -40 dBFS 且 p95−p10 > 15dB）。浏览器
        AGC 生效时电平已被拉回正常、不会到这里——本提示兜底 AGC 救不回的
        场景（系统输入音量近零 / 浏览器无 AGC / 超出最大增益）。ASR 特征
        归一化使纯低电平不影响识别，真正代价是信噪比低；事后增益无法改善，
        故只提示不放大。每个开麦周期（listen:start 之间）至多一次。
        """
        logger.info("持续低电平提示：session=%s p95=%.1f p10=%.1f delta=%.1f",
                    self.state.session.id, reading.p95, reading.p10, reading.delta)
        await self._send({
            "type": "audio.low_level",
            "dbfs": round(reading.p95, 1),
            "i18n_key": Keys.WS_AUDIO_LOW_LEVEL.value,
            "i18n_params": {},
            "message": i18n_t(Keys.WS_AUDIO_LOW_LEVEL, locale=self.state.locale),
        })

    async def _on_utterance(self, text: str, is_final: bool, start_sample: int) -> None:
        """管线产出整句 → 建段（标脏）+ 推 asr + 调度去抖落盘。

        落盘去抖（5s 或 N 脏段双触发）；辅导重算由 engine 事件驱动触发
        （on_utterance 武装防抖）。每条 ASR 结果仅更新 transcript + 推送客户端。
        """
        if not text:
            return
        async with self._utterance_lock:
            limit = self.policy.transcript_soft_limit
            if limit > 0 and len(self.state.transcript) >= limit:
                # 软上限：截断最早段，保留最近 limit-1 段后再 append
                self.state.transcript = self.state.transcript[-(limit - 1):]
            seg = TranscriptSegment(
                seg_id=self.state.next_seg_id(),
                start_ms=int(start_sample / 16),
                speaker="unknown",
                text=text,
                final=is_final,
            )
            self.state.transcript.append(seg)
            self._dirty_segments += 1
        logger.info("新转写段：[%s] final=%s %s", seg.seg_id, is_final, redact_text(seg.text))
        await self._send({
            "type": "asr",
            "seg_id": seg.seg_id,
            "start_ms": seg.start_ms,
            "speaker": seg.speaker,
            "text": seg.text,
            "final": is_final,
        })
        self._schedule_flush()
        self.engine.on_utterance()
        _touch(self.state.session.id)

    def _schedule_flush(self) -> None:
        """调度去抖落盘：脏段达阈值立即落盘，否则起去抖定时器。单槽（最多一个在途落盘任务）。"""
        if self._dirty_segments >= self._flush_dirty_segments:
            if self._flush_task is not None and not self._flush_task.done():
                self._flush_task.cancel()
            self._flush_task = asyncio.create_task(self._flush_now())
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_after())

    async def _flush_after(self) -> None:
        """去抖定时器：窗口到期后落盘（被取消时不落盘——由 _force_flush 负责）。"""
        await asyncio.sleep(self._flush_interval_s)
        await self._flush_now()

    async def _flush_now(self) -> None:
        """去抖触发的落盘：仅当有脏转写段时落盘（仅 transcript 分组脏）。"""
        async with self._utterance_lock:
            if self._dirty_segments == 0:
                return
            await self._save_now(fields={"transcript"})

    async def _save_now(self, *, fields=None) -> None:
        """实际落盘 + 清零脏段计数（调用方持 _utterance_lock）。

        仅在保存成功后清零；失败则保留计数，下次调度重试（不抛——避免拖垮 flush 任务或生命周期调用方）。
        fields 收窄写入分组（None=全写）。
        """
        try:
            await self._save_state(fields=fields)
        except Exception:  # noqa: BLE001
            logger.exception("落盘 save_state 失败：session=%s", self.state.session.id)
            return
        self._dirty_segments = 0

    async def _force_flush(self) -> None:
        """生命周期（listen_stop/end/unbind）强制落盘：取消去抖，无条件保存全部状态（含 consumed_seq）。"""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
            self._flush_task = None
        async with self._utterance_lock:
            await self._save_now()

    async def _send(self, msg: dict) -> None:
        """出站：经缓冲三分类 → 注入的 send 回调。critical 入缓冲待 replay。"""
        self.outbound.retain_critical(msg)
        await self._raw_send(msg)

    async def _raw_send(self, msg: dict) -> None:
        if self._send_fn is None:
            return
        async with self._send_lock:
            ok = await safe_send(self._send_fn, msg)
            if not ok:
                self._send_dead = True

    async def _save_state(self, *, fields=None) -> None:
        await interview_repo.save_state_auto(self.state, fields=fields)

    async def _persist_for_recompute(self) -> None:
        """engine 重算落盘经 _utterance_lock 串行，避免与 _on_utterance 建段交错。

        仅 coaching 分组变（items/coverage/skipped），transcript 未动，收窄避免全量重写。
        """
        async with self._utterance_lock:
            await self._save_state(fields={"coaching"})


class RuntimeRegistry:
    """会话运行时寄存：存活窗口内保留 Runtime（管线+引擎不重建）。

    _active 跟踪在线（WS 已 bind）runtime；断连 park 把它从 _active 移入 _parked
    并启动存活窗口定时器；窗口内重连 get_or_create 取回（取消定时器，复用 Runtime，
    回到 _active）；窗口过期 / end 则 drop（同时清 _active 和 _parked，Runtime 销毁）。
    与 manager 的 SessionStatus 存活窗口并行：registry 管内存 Runtime，manager 管持久化状态。

    不变量：
    - _active 与 _parked 互斥（同一 session_id 不同时存在）
    - park/drop 内部完成 _active 的移除；handler 不直接调 unregister
    - get 统一查找 _active 与 _parked（调用方无需关心 runtime 当前处于哪种状态）
    """

    def __init__(self) -> None:
        self._active: dict[str, SessionRuntime] = {}
        self._parked: dict[str, tuple[SessionRuntime, asyncio.Task]] = {}
        self._terminating: set[str] = set()

    def register(self, session_id: str, runtime: SessionRuntime) -> None:
        """注册在线 runtime（由 get_or_create 在新建/重连两条路径内部调用）。"""
        self._active[session_id] = runtime

    def unregister(self, session_id: str) -> None:
        """解绑在线 runtime：仅清 _active，不清 _parked。"""
        self._active.pop(session_id, None)

    def get_or_create(
        self,
        session_id: str,
        state: SessionState,
        policy: Optional[SessionPolicy] = None,
    ) -> SessionRuntime:
        """重连取回寄存的 Runtime（取消定时器，回到 _active）；首次则新建并注册。

        同步初始化（ConfigStore._cache 注入）由调用方调 runtime.ainit() 触发。
        """
        if session_id in self._parked:
            runtime, task = self._parked.pop(session_id)
            task.cancel()
            if runtime._fsm.is_terminated:
                # terminated runtime 不可复用（listen_start 会撞 terminated→live 崩）：
                # 丢弃，落到下方新建一条全新 runtime。
                logger.warning("复用的运行时已终止，改为新建：session=%s", session_id)
            else:
                self._refresh_session_fields(runtime, state.session)
                self._active[session_id] = runtime
                logger.info("会话运行时复用（重连取回）：session=%s state=%s",
                            session_id, runtime._fsm.state.value)
                return runtime
        # 已在线（并发 bind 同一 session）：复用现有，不新建
        existing = self._active.get(session_id)
        if existing is not None and not existing._fsm.is_terminated:
            return existing
        if existing is not None:
            logger.warning("在线运行时已终止，替换为新实例：session=%s", session_id)
        runtime = SessionRuntime(state, policy)
        self._active[session_id] = runtime
        logger.info("会话运行时新建：session=%s", session_id)
        return runtime

    @staticmethod
    def _refresh_session_fields(runtime: "SessionRuntime", fresh: Session) -> None:
        """寄存复用前，把 runtime 快照的会话级字段刷成 DB 现值。

        断连寄存期间用户可 PATCH base_info/goal（仅 suspended 态可编辑），而落盘时
        会话级字段整段写入——不刷新的话，重连后第一次落盘就把旧快照盖回 DB，用户
        的编辑无声丢失。consumed_seq 不刷：seq 游标归连接管线管，runtime 是权威。
        其余字段（status/timestamps）也以 DB 为准，runtime 不拥有它们。
        """
        stale = runtime.state.session
        stale.template_id = fresh.template_id
        stale.template_version = fresh.template_version
        stale.status = fresh.status
        stale.user_id = fresh.user_id
        stale.base_info = fresh.base_info
        stale.goal = fresh.goal
        stale.first_batch_generated = fresh.first_batch_generated
        stale.created_at = fresh.created_at
        stale.started_at = fresh.started_at
        stale.ended_at = fresh.ended_at

    def park(
        self,
        session_id: str,
        runtime: SessionRuntime,
        ttl_s: float,
        on_expire: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """断连时寄存 Runtime：从 _active 移入 _parked，启动存活窗口定时器。

        过期则 end() Runtime + on_expire；重连窗口内 get_or_create 取回。
        TERMINATED 的 runtime 不寄存（已销毁，重连应建新）——直接清理账目。
        """
        if runtime._fsm.is_terminated:
            logger.info("运行时已终止，跳过寄存：session=%s — 丢弃", session_id)
            self._active.pop(session_id, None)
            self.drop(session_id)
            return
        state = runtime._fsm.state
        if state is RuntimeState.LIVE:
            logger.warning(
                "运行时在 LIVE 态被寄存：session=%s（正常断连应先 unbind 到 suspended；活连接被寄存属异常）",
                session_id,
            )
        else:
            logger.info("运行时已寄存（存活窗口计时）：session=%s state=%s", session_id, state.value)
        self._active.pop(session_id, None)  # 从 _active 移除
        self.drop(session_id)  # 取消既有 _parked 定时器

        async def _expire() -> None:
            try:
                await asyncio.sleep(ttl_s)
                entry = self._parked.pop(session_id, None)
                if entry is None:
                    return
                runtime_, _ = entry
                # P1-4: end() 期间标记 terminating，让并发重连拒绝。
                # 否则该 session 此刻既不在 _active 也不在 _parked，重连 get_or_create
                # 会落空 → 新建孤儿 runtime 漏进 _active 且无人回收。
                self._terminating.add(session_id)
                try:
                    logger.info("运行时存活窗口到期，开始销毁：session=%s", session_id)
                    await runtime_.end()
                    if on_expire is not None:
                        await on_expire(session_id)
                finally:
                    self._terminating.discard(session_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("存活窗口到期销毁运行时失败：session=%s", session_id)

        self._parked[session_id] = (runtime, asyncio.create_task(_expire()))

    def drop(self, session_id: str) -> None:
        """同时清 _active 和 _parked（取消定时器）。"""
        self._active.pop(session_id, None)
        task = self._parked.pop(session_id, (None, None))[1]
        if task is not None:
            task.cancel()

    def get(self, session_id: str) -> Optional[SessionRuntime]:
        """统一查找：先 _active 后 _parked。调用方无需区分 runtime 当前状态。"""
        active = self._active.get(session_id)
        if active is not None:
            return active
        entry = self._parked.get(session_id)
        return entry[0] if entry else None

    def get_active(self, session_id: str) -> Optional[SessionRuntime]:
        """仅查 _active（在线 bound runtime）。"""
        return self._active.get(session_id)

    def is_terminating(self, session_id: str) -> bool:
        """runtime 是否正在 _expire 的 end() 中（liveness 已过）。

        仅在 liveness_window_s 到期后、end() 完成前的秒级窗口内为真。此窗口内
        重连应拒绝（runtime 正在销毁），由 handler 在 get_or_create 之前检查。
        """
        return session_id in self._terminating

    def all_active(self) -> list[SessionRuntime]:
        """所有在线（bound）runtime 列表。"""
        return list(self._active.values())

    def all_parked(self) -> list[SessionRuntime]:
        """所有 parked runtime 列表。"""
        return [entry[0] for entry in self._parked.values()]

    def all_runtimes(self) -> list[SessionRuntime]:
        """_active + _parked 全部 runtime（shutdown drain 用）。"""
        return self.all_active() + self.all_parked()


# 进程级单例（单 worker 部署）
registry = RuntimeRegistry()
