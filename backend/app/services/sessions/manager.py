"""会话生命周期管理：状态机 + 存活窗口 + idle 看门狗 + 同用户并发限制。

连接生命周期 ≠ 会话生命周期：协议断≠会话断。
- WS 断开：存活窗口（_grace）处理，窗口内重连复用 Runtime。
- idle 超时：watchdog（_idle_task + _last_activity_at）处理，自动转 SUSPENDED。
- 手动 end：用户主动结束 → ENDED。

in-memory _active 缓存 + 存活窗口 + watchdog 定时器是单进程的
（多 worker 需 Redis 共享）。

所有 DB 操作走 Repository 的 *_auto 方法（import-linter 契约：services 禁裸 SessionLocal）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.core.config_store import get_max_concurrent, get_session_runtime_config
from app.core.exceptions import ConcurrentLimitError, IllegalTransitionError
from app.domain.session import Session, SessionStatus
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.log_events import log_event
from app.services.sessions.runtime import registry
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template

logger = logging.getLogger(__name__)

# 合法状态转换
_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.SETTING_UP, SessionStatus.ENDED},
    SessionStatus.SETTING_UP: {SessionStatus.IN_PROGRESS, SessionStatus.ENDED},
    SessionStatus.IN_PROGRESS: {SessionStatus.SUSPENDED, SessionStatus.ENDED},
    SessionStatus.SUSPENDED: {SessionStatus.IN_PROGRESS, SessionStatus.ENDED},
    SessionStatus.ENDED: {SessionStatus.EXTRACTING},
    SessionStatus.EXTRACTING: {SessionStatus.DONE},
}


class SessionManager:
    def __init__(self) -> None:
        self._active: dict[str, SessionState] = {}
        self._grace: dict[str, asyncio.Task] = {}
        # idle 看门狗：每 idle_check_interval_s 扫一次 _active
        self._idle_task: Optional[asyncio.Task] = None
        self._last_activity_at: dict[str, float] = {}
        # idle 配置（每次 start_idle_watchdog 时刷新）
        self._idle_timeout_s: float = 120.0
        self._idle_check_interval_s: float = 30.0
        # 全局进程内 Lock，串行化 start/resume 的 count_active→save 临界区，消除 TOCTOU
        #（并发口径是全局 = FunASR 房间容量，故不同用户并发 start 也须串行）。
        # 多 worker 推迟 v2（需 Redis 共享计数 + 分布式锁）。
        self._start_lock = asyncio.Lock()

    # ---- 查询 ----
    async def get(self, session_id: str) -> Optional[SessionState]:
        if session_id in self._active:
            return self._active[session_id]
        return await interview_repo.get_state_auto(session_id)

    async def list_for_user(self, user_id: str) -> list[Session]:
        return await interview_repo.list_by_user_auto(user_id)

    # ---- 创建 ----
    async def create(
        self,
        user_id: str,
        template_id: str,
        base_info: Optional[dict] = None,
        goal: Optional[str] = None,
    ) -> SessionState:
        tpl = get_template(template_id)
        if tpl is None:
            raise KeyError(f"template not found: {template_id}")
        session = Session(
            id=str(uuid4()),
            template_id=template_id,
            template_version=tpl.version,
            user_id=user_id,
            status=SessionStatus.CREATED,
            base_info=base_info or {},
            goal=goal,
            created_at=datetime.now(timezone.utc),
        )
        state = SessionState.initial(session, tpl)
        await interview_repo.save_state_auto(state)
        log_event("session_created", session=session.id, user=user_id,
                  template=template_id, status="created")
        return state

    # ---- 状态转换 ----
    async def _transition(self, state: SessionState, to: SessionStatus) -> None:
        if to not in _TRANSITIONS.get(state.status, set()):
            raise IllegalTransitionError(
                f"非法状态转换: {state.status.value} → {to.value}"
            )
        state.session.status = to
        await interview_repo.save_state_auto(state)

    async def start(self, session_id: str) -> SessionState:
        """→ in_progress。WS hello 调；含全局并发限制。"""
        state = await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        user_id = state.user_id
        async with self._start_lock:  # 全局串行化 count_active→save，消除 TOCTOU
            if state.status == SessionStatus.IN_PROGRESS:  # 幂等（重连自己的活跃场）
                self._active[session_id] = state
                self.touch(session_id)
                return state

            active = await interview_repo.count_active_auto()
            limit = await get_max_concurrent()
            if active >= limit:
                raise ConcurrentLimitError(f"活跃访谈数已达上限（{limit}）")

            if state.status == SessionStatus.CREATED:
                await self._transition(state, SessionStatus.SETTING_UP)
            await self._transition(state, SessionStatus.IN_PROGRESS)
            if state.session.started_at is None:
                state.session.started_at = datetime.now(timezone.utc)
            await interview_repo.save_state_auto(state)
            self._active[session_id] = state
            self.touch(session_id)
            log_event("session_started", session=session_id, user=user_id,
                      status="in_progress")
            return state

    async def end(self, session_id: str) -> SessionState:
        state = self._active.pop(session_id, None) or await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        self._cancel_grace(session_id)
        self._last_activity_at.pop(session_id, None)
        if state.status != SessionStatus.ENDED:
            await self._transition(state, SessionStatus.ENDED)
        if state.session.ended_at is None:
            state.session.ended_at = datetime.now(timezone.utc)
        await interview_repo.save_state_auto(state)
        log_event("session_ended", session=session_id, user=state.user_id,
                  reason="manual", status="ended")
        return state

    async def update(
        self,
        session_id: str,
        base_info: Optional[dict],
        goal: Optional[str],
    ) -> SessionState:
        """编辑基础信息/目标。仅未开始(created)或暂停(suspended)态可编辑。"""
        state = await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        if state.status not in (SessionStatus.CREATED, SessionStatus.SUSPENDED):
            raise IllegalTransitionError(f"当前状态({state.status.value})不可编辑")
        merged = {**state.session.base_info, **base_info} if base_info is not None else None
        if ((goal is not None and goal != state.session.goal)
                or (merged is not None and merged != state.session.base_info)):
            # 目标/背景实际变更，旧首评作废：transcript 为空时下次进入会重新生成
            state.session.first_batch_generated = False
        if base_info is not None:
            state.session.base_info = {**state.session.base_info, **base_info}
        if goal is not None:
            state.session.goal = goal
        await interview_repo.save_state_auto(state)
        return state

    async def delete(self, session_id: str) -> None:
        """删除访谈。进行中/连接中(setting_up/in_progress)的 live 会话不可删。

        先拆除 registry 中寄存的运行时，再删 DB 行——顺序不可颠倒。寄存 runtime 的
        存活窗口到期会跑 runtime.end() → save_state，而 save_state 在记录缺失时会
        重建行；若先删行、后到期 end()，被删访谈会被「复活」成僵尸行（grace 挂起态
        删除尤其易触发）。故先 drop 取消存活定时器、再 end() 释放 ASR、最后删行。
        """
        state = await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        if state.status in (SessionStatus.IN_PROGRESS, SessionStatus.SETTING_UP):
            raise IllegalTransitionError(f"进行中的访谈不可删除(当前:{state.status.value})")
        runtime = registry.get(session_id)
        registry.drop(session_id)  # 取消 parked 存活定时器，杜绝过期 end() 复活
        if runtime is not None:
            try:
                await runtime.end()  # 此时行尚未删，落盘只更新既有行，无害
            except Exception:  # noqa: BLE001
                logger.exception("删除访谈时关闭运行时失败：session=%s", session_id)
        self._active.pop(session_id, None)
        self._last_activity_at.pop(session_id, None)
        self._cancel_grace(session_id)
        await interview_repo.delete_auto(session_id)
        log_event("session_deleted", session=session_id, user=state.user_id,
                  status="deleted")

    # ---- 存活窗口（WS 断线用）----
    def _cancel_grace(self, session_id: str) -> None:
        task = self._grace.pop(session_id, None)
        if task:
            task.cancel()

    async def on_disconnect(self, session_id: str) -> None:
        """WS 断开：清 activity（避免与 grace 重复判） + 启存活窗口定时器。"""
        self.clear_activity(session_id)
        if session_id in self._grace:
            return
        self._grace[session_id] = asyncio.create_task(self._grace_expire(session_id))

    async def _grace_expire(self, session_id: str) -> None:
        try:
            cfg = await get_session_runtime_config()
            await asyncio.sleep(cfg["grace_period_s"])
            state = self._active.get(session_id)
            if state and state.status == SessionStatus.IN_PROGRESS:
                await self._transition(state, SessionStatus.SUSPENDED)
                logger.info("会话已挂起（存活窗口到期）：%s", session_id)
                # P0-2: 只清 manager 自己的进程内账目。
                # 不调 registry.drop / runtime.end()——runtime（ASR/LLM 实例）归
                # registry，由 registry._expire 在 liveness_window_s 到期时销毁。
                self._active.pop(session_id, None)
                self._last_activity_at.pop(session_id, None)
                self._cancel_grace(session_id)
        except asyncio.CancelledError:
            pass

    async def on_reconnect(self, session_id: str) -> Optional[SessionState]:
        self._cancel_grace(session_id)
        state = await self.get(session_id)
        if state and state.status == SessionStatus.SUSPENDED:
            # 恢复成 in_progress 前须复核全局上限：suspended 本身不占名额，但一旦
            # 恢复就重新持有 live 运行时。与 start() 同一把 _start_lock，避免恢复与
            # 新建并发导致超额。IN_PROGRESS 的普通重连不走这里（它本就是那场活跃）。
            async with self._start_lock:
                state = await self.get(session_id)  # 临界区内重取，防状态已变
                if state and state.status == SessionStatus.SUSPENDED:
                    active = await interview_repo.count_active_auto()
                    limit = await get_max_concurrent()
                    if active >= limit:
                        raise ConcurrentLimitError(f"活跃访谈数已达上限（{limit}）")
                    await self._transition(state, SessionStatus.IN_PROGRESS)
        if state is not None:
            self._active[session_id] = state
            self.touch(session_id)
        return state

    # ---- Activity tracking + idle watchdog ----
    def touch(self, session_id: str) -> None:
        """标记会话刚刚有活动（被 Runtime 入站 API 或 manager 自己调）。"""
        if session_id in self._active:
            self._last_activity_at[session_id] = time.monotonic()

    def clear_activity(self, session_id: str) -> None:
        """WS 断线时清 activity，避免 grace 60s + idle 120s 重复判。"""
        self._last_activity_at.pop(session_id, None)

    def start_idle_watchdog(self) -> None:
        """lifespan startup 调一次。"""
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._idle_watchdog_loop())
            logger.info("空闲看门狗已启动（检查间隔=%ss，超时阈值=%ss）",
                        self._idle_check_interval_s, self._idle_timeout_s)

    async def stop_idle_watchdog(self) -> None:
        """lifespan shutdown 调一次。"""
        if self._idle_task is not None:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
            self._idle_task = None
            logger.info("空闲看门狗已停止")

    async def _idle_watchdog_loop(self) -> None:
        """每 idle_check_interval_s 扫一次 _active，把 idle 超时的会话转 SUSPENDED。

        拉配置：每次循环开头读一次，允许 UI 调参后下一轮生效（无需重启）。
        """
        try:
            cfg = await get_session_runtime_config()
            self._idle_timeout_s = cfg["idle_timeout_s"]
            self._idle_check_interval_s = cfg["idle_check_interval_s"]
        except Exception:  # noqa: BLE001
            logger.exception("空闲看门狗读取配置失败，使用默认值")

        while True:
            await asyncio.sleep(self._idle_check_interval_s)
            try:
                cfg = await get_session_runtime_config()
                self._idle_timeout_s = cfg["idle_timeout_s"]
                self._idle_check_interval_s = cfg["idle_check_interval_s"]
            except Exception:  # noqa: BLE001
                pass

            now = time.monotonic()
            for sid, state in list(self._active.items()):
                if state.status != SessionStatus.IN_PROGRESS:
                    continue
                last = self._last_activity_at.get(sid)
                if last is None:
                    continue
                idle_for = now - last
                if idle_for >= self._idle_timeout_s:
                    try:
                        await self._suspend_idle(sid, idle_for)
                    except Exception:  # noqa: BLE001
                        logger.exception("空闲挂起失败：session=%s", sid)

    async def _suspend_idle(self, session_id: str, idle_for: float) -> None:
        """idle 超时：关 ASR（runtime.suspend）+ _transition(SUSPENDED) + 清理 in-memory。

        runtime.suspend 发 session.suspended + 4403 关 WS——挂起可继续，
        不能复用 end() 的 session.ended + 4406（那会让前端进只读态，
        与 DB 落的 suspended 矛盾）。
        """
        runtime = registry.get(session_id)
        if runtime is not None:
            try:
                await runtime.suspend()
            except Exception:  # noqa: BLE001
                logger.exception("空闲挂起时关闭运行时失败：session=%s", session_id)

        state = self._active.get(session_id)
        if state is None:
            return
        await self._transition(state, SessionStatus.SUSPENDED)

        self._active.pop(session_id, None)
        self._last_activity_at.pop(session_id, None)
        self._cancel_grace(session_id)
        registry.drop(session_id)

        log_event("session_idle_suspended",
                  session=session_id, user=state.user_id,
                  idle_s=round(idle_for, 1), status="suspended")


manager = SessionManager()
