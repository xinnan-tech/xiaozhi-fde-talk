"""访谈会话 Repository。

封装 InterviewRecord 的 CRUD，services 层通过此 Repository 访问持久化，不直接用 SessionLocal。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.coaching import CoachingItem
from app.domain.session import Session, SessionStatus, TranscriptSegment
from app.domain.session_state import SessionState
from app.persistence.models import InterviewRecord


def _record_to_session(rec: InterviewRecord) -> Session:
    return Session(
        id=rec.id,
        template_id=rec.template_id,
        template_version=rec.template_version,
        template_snapshot=rec.template_snapshot,
        status=SessionStatus(rec.status),
        user_id=rec.user_id,
        base_info=rec.base_info or {},
        goal=rec.goal,
        first_batch_generated=bool(rec.first_batch_generated),
        consumed_seq=rec.consumed_seq,
        created_at=rec.created_at,
        started_at=rec.started_at,
        ended_at=rec.ended_at,
    )


def _record_to_state(rec: InterviewRecord) -> SessionState:
    return SessionState(
        session=_record_to_session(rec),
        items=[CoachingItem(**d) for d in (rec.coaching_items or [])],
        skipped_ids=set(rec.skipped_ids or []),
        ignored_ids=set(rec.ignored_ids or []),
        coverage=dict(rec.coverage_index or {}),
        transcript=[TranscriptSegment(**d) for d in (rec.transcript or [])],
    )


class InterviewRepository:
    """访谈会话持久化。所有方法接受一个 AsyncSession（由调用方管理事务/生命周期）。"""

    def __init__(self) -> None:
        # per-session 写串行锁。manager 定时器与 runtime flush 并发对同一
        # session 落盘（各自独立连接/事务），串行化 DB 写避免 SQLite 'database is
        # locked' 与事务交错。单进程粒度；共享 SessionState 下无 lost update。
        self._save_locks: dict[str, asyncio.Lock] = {}

    def _save_lock(self, session_id: str) -> asyncio.Lock:
        # setdefault 同步完成（无 await），事件循环内原子，无 check-then-act 竞态。
        return self._save_locks.setdefault(session_id, asyncio.Lock())

    def _release_save_lock(self, session_id: str, lock: asyncio.Lock) -> None:
        """save_state 用完回收：字典只增不减会随历史会话数缓慢泄漏内存。

        仅当字典里仍是这把锁、且无排队等待者时回收。检查发生在持有锁的
        同步代码段末尾（检查到释放锁之间无 await），新等待者不可能插进
        这个窗口；已排队的等待者会被 _waiters 命中而不回收——若此刻删掉，
        后来者会 setdefault 到一把新锁并与其并行进临界区，串行化就破了。
        （_waiters 是 asyncio 私有属性，但 CPython 3.10+ 稳定存在。）
        """
        if self._save_locks.get(session_id) is lock and not lock._waiters:
            del self._save_locks[session_id]
    async def get_state(self, db: AsyncSession, session_id: str) -> Optional[SessionState]:
        rec = await db.get(InterviewRecord, session_id)
        return _record_to_state(rec) if rec else None

    async def get_state_auto(self, session_id: str) -> Optional[SessionState]:
        """自动管理 session 的 get_state（services 层用，不直接 import SessionLocal）。"""
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.get_state(db, session_id)

    async def get_session(self, db: AsyncSession, session_id: str) -> Optional[Session]:
        rec = await db.get(InterviewRecord, session_id)
        return _record_to_session(rec) if rec else None

    async def get_session_auto(self, session_id: str) -> Optional[Session]:
        """自动管理 session 的 get_session（存在性检查 / 轻量单行读取）。"""
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.get_session(db, session_id)

    async def save_state(
        self, db: AsyncSession, state: SessionState, *, fields: Optional[set[str]] = None
    ) -> None:
        """落盘。fields 收窄写入分组（None=全写）：

        - {"transcript"}：仅 transcript（utterance 去抖落盘）
        - {"coaching"}：coaching_items + skipped/ignored/coverage（重算落盘）
        - None：全写（skip/ignore/shutdown/生命周期 force_flush——兜底，不丢字段）
        会话元信息（status/consumed_seq/timestamps 等）始终写。
        """
        lock = self._save_lock(state.session.id)
        async with lock:
            try:
                rec = await db.get(InterviewRecord, state.session.id)
                if rec is None:
                    rec = InterviewRecord(id=state.session.id)
                    db.add(rec)
                s = state.session
                # ended 是终态：寄存 runtime 的旧 SessionState 快照（manager 从 DB
                # 新载入的是另一个对象）不得把已结束的会话写回进行中/挂起。
                # 其余字段照写——旧快照的 transcript 往往反而是最新的。
                is_regression = (
                    rec.status == "ended" and s.status.value != "ended"
                )
                rec.template_id = s.template_id
                rec.template_version = s.template_version
                # 快照只写不清：创建时固化的模板快照是「访谈按当时模板执行」的
                # 依据，一旦被覆成 NULL 就再也回不来（resolve_template 会静默回退
                # 当前缓存模板，模板被改过的老访谈就串味了）。会话生命周期内
                # save_state 会被反复调用（状态转换、消息处理、去抖落盘），其中
                # 部分调用方持有的 SessionState 可能没带快照——故仅在有值时写入。
                if s.template_snapshot is not None:
                    rec.template_snapshot = s.template_snapshot
                if not is_regression:
                    rec.status = s.status.value
                rec.user_id = s.user_id
                rec.base_info = s.base_info
                rec.goal = s.goal
                rec.first_batch_generated = s.first_batch_generated
                rec.consumed_seq = s.consumed_seq
                rec.created_at = s.created_at
                rec.started_at = s.started_at
                if not is_regression or rec.ended_at is None:
                    rec.ended_at = s.ended_at
                if fields is None or "transcript" in fields:
                    rec.transcript = [seg.model_dump(mode="json") for seg in state.transcript]
                if fields is None or "coaching" in fields:
                    rec.coaching_items = [it.model_dump(mode="json") for it in state.items]
                    rec.skipped_ids = sorted(state.skipped_ids)
                    rec.ignored_ids = sorted(state.ignored_ids)
                    rec.coverage_index = dict(state.coverage)
                await db.commit()
            finally:
                # 持锁的同步段末尾回收（见 _release_save_lock 的竞态说明）
                self._release_save_lock(state.session.id, lock)

    async def save_state_auto(
        self, state: SessionState, *, fields: Optional[set[str]] = None
    ) -> None:
        """自动管理 session 的 save_state（供不便持有 AsyncSession 的 services 调用方使用）。

        services 层不应直接 import persistence.db.SessionLocal（import-linter 契约），
        改走此方法：SessionLocal 由 persistence 层自己管理。
        """
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            await self.save_state(db, state, fields=fields)

    async def list_by_user(
        self, db: AsyncSession, user_id: str, statuses: Optional[list[str]] = None
    ) -> list[Session]:
        """列出某用户的访谈会话。可选按 status 过滤（字符串值，与 count_active 口径一致）。

        statuses=None → 不过滤；非空 → 加 `status IN (...)`。
        """
        stmt = (
            select(InterviewRecord)
            .where(InterviewRecord.user_id == user_id)
        )
        if statuses:
            stmt = stmt.where(InterviewRecord.status.in_(statuses))
        stmt = stmt.order_by(InterviewRecord.created_at.desc())
        res = await db.execute(stmt)
        return [_record_to_session(r) for r in res.scalars()]

    async def list_by_user_auto(
        self, user_id: str, statuses: Optional[list[str]] = None
    ) -> list[Session]:
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.list_by_user(db, user_id, statuses=statuses)

    async def list_records_by_user_auto(
        self, user_id: str, statuses: Optional[list[str]] = None
    ) -> list[InterviewRecord]:
        """与 list_by_user_auto 类似但返回 ORM 行（summary 派生用，要 JSON 列）。"""
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            stmt = (
                select(InterviewRecord)
                .where(InterviewRecord.user_id == user_id)
            )
            if statuses:
                stmt = stmt.where(InterviewRecord.status.in_(statuses))
            stmt = stmt.order_by(InterviewRecord.created_at.desc())
            res = await db.execute(stmt)
            return list(res.scalars())

    async def count_active(self, db: AsyncSession) -> int:
        """全局活跃会话数（并发上限用）。

        活跃 = 持有 live 运行时（setting_up / in_progress）。suspended 不计数——
        其 ASR/LLM 运行时已释放、不占房间；恢复（on_reconnect）时会再次校验上限。
        口径是全局（跨用户合计）：上限匹配 FunASR 房间总容量，而非每用户配额。
        """
        res = await db.execute(
            select(func.count()).select_from(InterviewRecord).where(
                InterviewRecord.status.in_([
                    SessionStatus.SETTING_UP.value,
                    SessionStatus.IN_PROGRESS.value,
                ]),
            )
        )
        return int(res.scalar() or 0)

    async def count_active_auto(self) -> int:
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.count_active(db)

    async def delete_auto(self, session_id: str) -> bool:
        """删除访谈记录。返回是否确实删了一行。"""
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            rec = await db.get(InterviewRecord, session_id)
            if rec is None:
                return False
            await db.delete(rec)
            await db.commit()
            return True

    # ---- 统计卡聚合（A4）----
    # 注意：inProgress 统计口径 = setting_up + in_progress（不含 suspended；suspended 是「挂起可继续」，
    # 归入前端「进行中」tab 而非统计卡）。所有方法走 *_auto，services 层不裸 SessionLocal。

    async def count_in_progress_for_user_auto(self, user_id: str) -> int:
        from app.persistence.db import SessionLocal
        async with SessionLocal() as db:
            res = await db.execute(
                select(func.count()).select_from(InterviewRecord).where(
                    InterviewRecord.user_id == user_id,
                    InterviewRecord.status.in_([
                        SessionStatus.SETTING_UP.value, SessionStatus.IN_PROGRESS.value,
                    ]),
                )
            )
            return int(res.scalar() or 0)

    async def count_ended_in_week_for_user_auto(self, user_id: str, week_start_utc: datetime) -> int:
        from app.persistence.db import SessionLocal
        async with SessionLocal() as db:
            res = await db.execute(
                select(func.count()).select_from(InterviewRecord).where(
                    InterviewRecord.user_id == user_id,
                    InterviewRecord.status == SessionStatus.ENDED.value,
                    InterviewRecord.ended_at >= week_start_utc,
                )
            )
            return int(res.scalar() or 0)

    async def count_assist_discovery_for_user_auto(self, user_id: str) -> int:
        """AI 共发现问题数 = 用户名下所有会话的 coaching_items 总条数。

        含所有 session 状态（created/setting_up/in_progress/suspended/ended/extracting/done），
        含所有 item status（todo/new/done）。coaching_items 由「模板必问占位（must_ask seed）」
        +「AI 引擎实时新增」两部分组成；按用户口径「AI 一共发现了多少个问题」接受当前实现把
        两者都计入，不区分来源。
        """
        from app.persistence.db import SessionLocal
        async with SessionLocal() as db:
            res = await db.execute(
                select(InterviewRecord).where(InterviewRecord.user_id == user_id)
            )
            recs = list(res.scalars())
        total = 0
        for rec in recs:
            total += len(rec.coaching_items or [])
        return total

    async def count_interview_coverage_for_user_auto(self, user_id: str) -> int:
        """访谈命中问题数 = 用户名下所有会话的 coaching_items 中 status == 'done' 的条数。

        含所有 session 状态；仅统计 status == 'done' 的 item（已命中/已覆盖）。
        """
        from app.persistence.db import SessionLocal
        async with SessionLocal() as db:
            res = await db.execute(
                select(InterviewRecord).where(InterviewRecord.user_id == user_id)
            )
            recs = list(res.scalars())
        total = 0
        for rec in recs:
            for item in (rec.coaching_items or []):
                if item.get("status") == "done":
                    total += 1
        return total


# 单例（无状态，安全共享）
interview_repo = InterviewRepository()
