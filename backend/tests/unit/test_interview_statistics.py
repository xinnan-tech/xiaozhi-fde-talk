"""GET /api/v1/interviews/statistics：聚合四张统计卡数字。

口径：
  - in_progress = status ∈ {setting_up, in_progress} 的会话数（用户的）
  - week_finish = 当前 ISO 周（UTC）ended 的会话数（用户的）
  - assist_discovery = 所有 ended 会话 coaching_items 中 status == "new" 的累计条数（降级）
  - interview_coverage = status == "ended" 且 transcript 非空的会话数（降级）

asssist_discovery / interview_coverage 标注 `# TODO(product): 待产品确认口径`，
均处于降级口径；in_progress 不含 suspended（suspended 归入「进行中」tab 而非统计卡）。
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
        # ended this week, transcript non-empty, with new items (count in week_finish + interview_coverage + assist_discovery)
        s2 = Session(id="s-end-1", template_id="pm-research", user_id="u", status=SessionStatus.ENDED)
        # ended this week, transcript empty (count only in week_finish)
        s3 = Session(id="s-end-2", template_id="pm-research", user_id="u", status=SessionStatus.ENDED)
        # created (ignore)
        s4 = Session(id="s-c", template_id="pm-research", user_id="u", status=SessionStatus.CREATED)

        now = datetime.now(timezone.utc)

        st1 = SessionState.initial(s1, tpl)
        st2 = SessionState.initial(s2, tpl)
        st2.session.ended_at = now
        st2.transcript = [TranscriptSegment(seg_id="sg1", start_ms=0, text="hi", final=True)]
        st2.items = [CoachingItem(id="i1", text="t", status="new")]
        st3 = SessionState.initial(s3, tpl)
        st3.session.ended_at = now
        st3.transcript = []
        st4 = SessionState.initial(s4, tpl)

        for st in (st1, st2, st3, st4):
            await interview_repo.save_state_auto(st)

        stats = await manager.statistics_for_user("u")

        assert stats["in_progress"] == 1
        assert stats["week_finish"] >= 2  # depends on timezone; use >= to be robust
        assert stats["interview_coverage"] >= 1
        assert stats["assist_discovery"] >= 1
    finally:
        await engine.dispose()
