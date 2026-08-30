"""GET /api/v1/interviews：列表 summary 派生计数 + 展示字段。

`_session_summary(rec, tpl)` 接受 ORM 行 + 模板：派生
`pending_count / covered_count / ignored_count / asked_count / total_count` 计数 +
`title / interviewee / type / template_icon_url / status_type / recent_time` 展示字段。
detail 接口（`_state_detail(state)`）保持原签名。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.coaching import CoachingItem
from app.domain.session import Session, SessionStatus
from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template
from app.transport.http.routes.interviews import _session_summary


@pytest.fixture
def mem_db(monkeypatch):
    """内存库，隔离与其他 unit 测试的共享 DB 状态（防止 user='u' 撞名）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    return engine, factory


@pytest.mark.asyncio
async def test_session_summary_derives_counts_and_display_fields(mem_db):
    engine, factory = mem_db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        sid = "s-summary-1"
        tpl = get_template("pm-research")
        now = datetime.now(timezone.utc)
        sess = Session(
            id=sid,
            template_id="pm-research",
            user_id="u",
            status=SessionStatus.IN_PROGRESS,
            base_info={"title": "项目A", "project": "项目A", "interviewee": "张三"},
            goal="g",
            created_at=now,
            started_at=now,
        )
        state = SessionState.initial(sess, tpl)
        state.items = [
            CoachingItem(id="i1", text="t1", status="todo"),
            CoachingItem(id="i2", text="t2", status="new"),
            CoachingItem(id="i3", text="t3", status="done"),
        ]
        state.skipped_ids = {"sk1"}
        state.ignored_ids = {"ig1"}
        state.coverage = {"i3": ["hit-1"]}
        await interview_repo.save_state_auto(state)

        from app.persistence.models import InterviewRecord
        async with factory() as db:
            rec = await db.get(InterviewRecord, sid)

        summary = _session_summary(rec, tpl)
        assert summary["title"] == "项目A"
        assert summary["interviewee"] == "张三"
        assert summary["type"] == tpl.name
        assert summary["template_icon_url"] == tpl.icon_url
        assert summary["pending_count"] == 2
        assert summary["covered_count"] == 1
        assert summary["ignored_count"] == 1
        assert summary["asked_count"] == 1
        assert summary["total_count"] == 3
        assert summary["status_type"] == "info"

        # 清理：防污染共享 DB（user='u' 与 A2 test 撞名，A2 依赖精确的会话集合）
        await interview_repo.delete_auto(sid)
    finally:
        await engine.dispose()