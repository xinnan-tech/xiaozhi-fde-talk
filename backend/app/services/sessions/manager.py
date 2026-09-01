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
from datetime import datetime, timedelta, timezone
from typing import Container, Optional
from uuid import uuid4

from app.core.config_store import get_config_store, get_max_concurrent, get_session_runtime_config
from app.core.i18n import Keys
from app.core.i18n.errors import (
    I18nError,
    SessionConcurrentLimitError,
    SessionDeleteForbiddenError,
    SessionEditForbiddenError,
    SessionIllegalTransitionError,
)
# Legacy aliases: existing `except ConcurrentLimitError` / `except IllegalTransitionError`
# in transports/services continue to match because these names are the SAME class.
from app.core.exceptions import (
    ConcurrentLimitError,  # noqa: F401  (re-exported alias)
    IllegalTransitionError,  # noqa: F401  (re-exported alias)
)
from app.domain.session import Session, SessionStatus
from app.domain.template import Template
from app.persistence.models import InterviewRecord
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.log_events import log_event
from app.services.sessions.runtime import registry
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template, resolve_template
# TOCTOU 兜底：manager.update 必须对「本函数 GET 的最新快照 + PATCH 增量」merged 再跑
# 字节上限校验。route 层的 _validate_base_info_size 是基于它自己 GET 快照的 fast-fail，
# 与 manager.update 内部的 GET 不在同一临界区，并发 PATCH 可在两者之间先 commit。
# 故此处必须基于本函数的最新 GET 再校验一次（不依赖 route 层的过期快照）。
# 函数本身是纯校验，与 DB/HTTP 解耦，从 schemas 引出是合理的（routes 也从这里引）。
from app.transport.http.schemas import _validate_base_info_size

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
        # _stop_flag：被外部置位让 watchdog 跳出 sleep（lifespan shutdown 用）
        self._stop_flag: asyncio.Event = asyncio.Event()
        # _config_change_flag：cfg 改了让 watchdog 立刻重读+重排队；避免 30s
        # 区间下挂起要等当前 sleep 走完才反应
        self._config_change_flag: asyncio.Event = asyncio.Event()
        # ConfigStore._subscribers 是 WeakSet，临时 bound method 会被立即 GC；须持
        # 强引用，否则订阅静默失效，cfg 改动后 watchdog 仍睡满当前区间才反应
        self._config_change_sub = self._on_config_change
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

    async def list_for_user(
        self, user_id: str, statuses: Optional[list[SessionStatus]] = None
    ) -> list[Session]:
        raw = [s.value for s in statuses] if statuses else None
        return await interview_repo.list_by_user_auto(user_id, statuses=raw)

    async def list_summaries_for_user(
        self, user_id: str, statuses: Optional[list[SessionStatus]] = None
    ) -> list[tuple[InterviewRecord, Template]]:
        """返回 (InterviewRecord, Template) 列表给 summary 路由使用。"""
        raw = [s.value for s in statuses] if statuses else None
        recs = await interview_repo.list_records_by_user_auto(user_id, statuses=raw)
        out: list[tuple[InterviewRecord, Template]] = []
        for rec in recs:
            tpl = resolve_template(rec.template_id, rec.template_snapshot)
            out.append((rec, tpl))
        return out

    # ---- 统计卡（A4）----
    async def statistics_for_user(self, user_id: str) -> dict[str, int]:
        """返回四张统计卡数字（snake_case keys）。

        - in_progress: setting_up + in_progress 的会话数
        - week_finish: 当前 ISO 周（UTC 周一起算）ended 的会话数
        - assist_discovery: 用户名下所有 coaching_items 总条数（AI 共发现问题数）
        - interview_coverage: 用户名下所有 coaching_items 中 status == 'done' 的条数（访谈命中问题数）
        关系：interview_coverage ⊆ assist_discovery（已命中是已发现的子集；二者非互斥）。
        """
        now_utc = datetime.now(timezone.utc)
        week_start = now_utc - timedelta(days=now_utc.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        in_progress = await interview_repo.count_in_progress_for_user_auto(user_id)
        week_finish = await interview_repo.count_ended_in_week_for_user_auto(user_id, week_start)
        assist_discovery = await interview_repo.count_assist_discovery_for_user_auto(user_id)
        interview_coverage = await interview_repo.count_interview_coverage_for_user_auto(user_id)

        return {
            "in_progress": in_progress,
            "week_finish": week_finish,
            "assist_discovery": assist_discovery,
            "interview_coverage": interview_coverage,
        }

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
            # 创建时固化整份模板快照：此后模板编辑/演进不影响本访谈
            template_snapshot=tpl.model_dump(mode="json"),
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
            raise SessionIllegalTransitionError(
                from_state=state.status.value, to_state=to.value,
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
                raise SessionConcurrentLimitError(limit=limit)

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

    async def suspend(self, session_id: str) -> SessionState:
        """暂停访谈：仅变更状态为 suspended，不拆 runtime（管线由 WS listen:stop 暂停）。
        与 end 的区别：不做辅导终局重算，不关 WS，不设置 ended_at。
        """
        state = self._active.pop(session_id, None) or await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        self._cancel_grace(session_id)
        self._last_activity_at.pop(session_id, None)
        if state.status == SessionStatus.SUSPENDED:
            # 已经是 suspended，幂等跳过
            return state
        await self._transition(state, SessionStatus.SUSPENDED)
        await interview_repo.save_state_auto(state)
        log_event("session_suspended", session=session_id, user=state.user_id,
                  reason="manual", status="suspended")
        return state

    async def resume(self, session_id: str) -> SessionState:
        """继续访谈：将 suspended 状态的会话转回 in_progress。"""
        state = self._active.pop(session_id, None) or await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        async with self._start_lock:
            state = await self.get(session_id)
            if state.status == SessionStatus.IN_PROGRESS:
                self._active[session_id] = state
                self.touch(session_id)
                return state
            if state.status != SessionStatus.SUSPENDED:
                raise SessionIllegalTransitionError(
                    from_state=state.status.value, to_state="in_progress",
                )
            active = await interview_repo.count_active_auto()
            limit = await get_max_concurrent()
            if active >= limit:
                raise SessionConcurrentLimitError(limit=limit)
            await self._transition(state, SessionStatus.IN_PROGRESS)
        self._active[session_id] = state
        self.touch(session_id)
        log_event("session_resumed", session=session_id, user=state.user_id,
                  reason="manual", status="in_progress")
        return state

    async def update(
        self,
        session_id: str,
        base_info: Optional[dict],
        goal: Optional[str],
    ) -> SessionState:
        """编辑基础信息/目标。仅未开始(created)或暂停(suspended)态可编辑。

        TOCTOU 兜底：本函数内对「本函数 GET 的最新快照 + PATCH 增量」merged 再跑
        一次字节上限校验，挡住 route 层 GET 与本函数 GET 之间的并发 PATCH 累计
        放大——见 openrz 第二轮评审 #171。route 层的 _validate_base_info_size 是
        fast-fail（基于 route GET 快照；多数单请求场景足够），本层是最终一致性
        兜底（基于本函数 GET 快照）。两层都过则 merged 必然 ≤ 64KB 才落库。
        """
        state = await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        if state.status not in (SessionStatus.CREATED, SessionStatus.SUSPENDED):
            raise SessionEditForbiddenError(state=state.status.value)

        merged: Optional[dict] = None
        if base_info is not None:
            merged = {**state.session.base_info, **base_info}
            # 本函数 GET 是最新快照（与 route 层 GET 之间可能已有并发 PATCH commit）。
            # 串行 PATCH 累计若不在此处校验，merged 可绕过 BASE_INFO_TOTAL_MAX_BYTES
            # ——校验抛 I18nError(Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE, 422)，
            # 全局 I18nError handler 转 422 + 本地化 detail。
            _validate_base_info_size(merged)

        base_info_changed = merged is not None and merged != state.session.base_info
        goal_changed = goal is not None and goal != state.session.goal
        if base_info_changed or goal_changed:
            # 目标/背景实际变更，旧首评作废：transcript 为空时下次进入会重新生成
            state.session.first_batch_generated = False
        if merged is not None:
            state.session.base_info = merged
        if goal is not None:
            state.session.goal = goal
        await interview_repo.save_state_auto(state)
        return state

    async def set_item_status(
        self, session_id: str, item_id: str, action: str,
        valid_ids: Optional[Container[str]] = None,
    ) -> SessionState:
        """REST 端的 ignore/skip/unignore/unskip。不要求 runtime 存活。
        action ∈ {"ignore", "unignore", "skip", "unskip"}.

        valid_ids：可选，调用方传入当前访谈模板的合法 item_id 集合（即
        `template_snapshot["coaching"]["must_ask"]` 的 id 列表）。对
        `skip` / `ignore` 写入操作强制校验——错 id 直接 404，不污染
        DB（#164）。`unskip` / `unignore` 是 idempotent 的 discard，不校验
        （错 id 本就静默无操作，前端未渲染亦无害）。
        """
        if action not in ("ignore", "unignore", "skip", "unskip"):
            raise ValueError(f"unknown action: {action}")
        state = await self.get(session_id)
        if state is None:
            raise KeyError(session_id)
        if action in ("ignore", "skip") and valid_ids is not None and item_id not in valid_ids:
            # 路由层负责把这条 I18nError 转 404 + {detail, code}
            raise I18nError(Keys.HTTP_COACHING_ITEM_NOT_FOUND, http_status=404, item_id=item_id)
        if action == "ignore":
            state.ignored_ids.add(item_id)
        elif action == "unignore":
            state.ignored_ids.discard(item_id)
        elif action == "skip":
            state.skipped_ids.add(item_id)
        elif action == "unskip":
            state.skipped_ids.discard(item_id)
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
            raise SessionDeleteForbiddenError(state=state.status.value)
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
                # 只清 manager 自己的进程内账目。
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
            # WS 重连时：若会话处于 suspended，保持 suspended 不变。
            # 状态转回 in_progress 由用户点击"继续"按钮触发（listen:start 路径），
            # 而不是 WS 重连自动触发——避免网络抖动 WS 重连就把列表页状态刷回"进行中"。
            # SUSPENDED 不占活跃名额，无需校验并发上限。
            pass
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
            self._stop_flag.clear()
            self._config_change_flag.clear()
            self._idle_task = asyncio.create_task(self._idle_watchdog_loop())
            logger.info("空闲看门狗已启动（检查间隔=%ss，超时阈值=%ss）",
                        self._idle_check_interval_s, self._idle_timeout_s)
            # 订阅 session.* 改动：UI 调参后立即唤醒 watchdog 重读 cfg + 重排队，
            # 不必等当前 sleep 走完，避免 30s 区间下挂起要等 ~30s 才反应。
            # 仅在 task 新建时挂订阅：ConfigStore._subscribers 是 WeakSet，
            # 多次 add 不去重，重入 start_idle_watchdog 会累积 weak ref。
            get_config_store().subscribe(self._config_change_sub)

    async def stop_idle_watchdog(self) -> None:
        """lifespan shutdown 调一次。

        注意：不要 `await self._idle_task`——watchdog 循环内部 `_config_change_flag`
        Event 会在首次 wait() 时永久绑定到启动它的 loop，跨 loop 等待会抛
        "bound to a different event loop"（见 test_registration_status 单跑过、
        与 test_registration 同跑挂——manager 模块级单例，第二个 module 的 lifespan
        shutdown 时撞 loop 绑定）。只 set flag + cancel()，不等任务完成。
        """
        self._stop_flag.set()
        self._config_change_flag.set()
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        logger.info("空闲看门狗已停止")

    def _on_config_change(self, changed_keys: set[str]) -> None:
        """订阅回调：session.* 改动时打断 watchdog 当前 sleep，让它立刻重读 cfg。

        用 Event 触发而不是 cancel：cancel 会让 asyncio.sleep 抛 CancelledError，导致
        循环意外终止需重启；Event set 后下一次 wait_for 调用立刻返回，watchdog 继续循环。
        """
        if not any(k.startswith("session.") for k in changed_keys):
            return
        self._config_change_flag.set()

    async def _idle_watchdog_loop(self) -> None:
        """每 idle_check_interval_s 扫一次 _active，把 idle 超时的会话转 SUSPENDED。

        拉配置：每次循环开头读一次，允许 UI 调参后下一轮循环生效（无需重启）。
        cfg 改动通过订阅回调立即打断 sleep（避免 30s 区间下挂起要等一轮）。
        """
        while True:
            # 读 cfg；如被 cfg 改动事件打断，立刻再读一次
            try:
                cfg = await get_session_runtime_config()
                self._idle_timeout_s = cfg["idle_timeout_s"]
                self._idle_check_interval_s = cfg["idle_check_interval_s"]
            except Exception:  # noqa: BLE001
                logger.exception("空闲看门狗读取配置失败，使用默认值")

            # 等下一轮循环：timeout = 当前间隔；cfg 改动 / stop 提前唤醒
            try:
                await asyncio.wait_for(
                    self._config_change_flag.wait(),
                    timeout=self._idle_check_interval_s,
                )
                self._config_change_flag.clear()
                if self._stop_flag.is_set():
                    return
                continue  # cfg 改了，立刻重读 + 重排队
            except asyncio.TimeoutError:
                pass

            if self._stop_flag.is_set():
                return

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
