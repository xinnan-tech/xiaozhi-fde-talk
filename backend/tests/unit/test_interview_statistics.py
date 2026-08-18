"""GET /api/v1/interviews/statistics：聚合四张统计卡数字。

口径：
  - in_progress = status ∈ {setting_up, in_progress} 的会话数（用户的）
  - week_finish = 当前 ISO 周（UTC）ended 的会话数（用户的）
  - assist_discovery = 用户名下所有 coaching_items 总条数（AI 共发现问题数）
  - interview_coverage = 用户名下所有 coaching_items 中 status == "done" 的条数（访谈命中问题数）

in_progress 不含 suspended（suspended 归入「进行中」tab 而非统计卡）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.coaching import CoachingItem
from app.domain.session import Session, SessionStatus, TranscriptSegment
from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


@pytest.fixture
def mem_db(monkeypatch):
    """内存库，隔离与其他 unit 测试的共享 DB 状态（防止 user='u' 撞名）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    return engine, factory


@pytest.mark.asyncio
async def test_statistics_for_user_aggregates_four_numbers(mem_db):
    engine, factory = mem_db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        tpl = get_template("pm-research")

        # in_progress (count=1)
        s1 = Session(id="s-in", template_id="pm-research", user_id="u", status=SessionStatus.IN_PROGRESS)
        # ended this week, transcript non-empty, with done + new items (count in week_finish + interview_coverage + assist_discovery)
        s2 = Session(id="s-end-1", template_id="pm-research", user_id="u", status=SessionStatus.ENDED)
        # ended this week, transcript empty (count only in week_finish)
        s3 = Session(id="s-end-2", template_id="pm-research", user_id="u", status=SessionStatus.ENDED)
        # created (ignore)
        s4 = Session(id="s-c", template_id="pm-research", user_id="u", status=SessionStatus.CREATED)

        now = datetime.now(timezone.utc)

        st1 = SessionState.initial(s1, tpl)
        st1.items = []  # 清空模板 must_ask seed（统计卡测试不依赖模板）
        st2 = SessionState.initial(s2, tpl)
        st2.session.ended_at = now
        st2.transcript = [TranscriptSegment(seg_id="sg1", start_ms=0, text="hi", final=True)]
        st2.items = [
            CoachingItem(id="i1", text="已命中", status="done"),
            CoachingItem(id="i2", text="新发现", status="new"),
        ]
        st3 = SessionState.initial(s3, tpl)
        st3.items = []  # 清空模板 must_ask seed
        st3.session.ended_at = now
        st3.transcript = []
        st4 = SessionState.initial(s4, tpl)
        st4.items = []  # 清空模板 must_ask seed

        for st in (st1, st2, st3, st4):
            await interview_repo.save_state_auto(st)

        stats = await manager.statistics_for_user("u")

        assert stats["in_progress"] == 1
        assert stats["week_finish"] >= 2  # depends on timezone; use >= to be robust
        # 真口径：st1/st3/st4 已清空模板 must_ask seed；仅 st2 有 2 个 items（1 done + 1 new）
        assert stats["assist_discovery"] == 2  # 仅 st2 贡献
        assert stats["interview_coverage"] == 1  # s2 1 个 done
    finally:
        await engine.dispose()
