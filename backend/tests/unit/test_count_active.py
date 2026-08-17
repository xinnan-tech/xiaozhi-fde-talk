"""count_active 语义：全局活跃会话数（并发上限用）。

活跃 = 持有 live 运行时（setting_up / in_progress）。suspended 不计数——
其 ASR/LLM 运行时已释放、不占房间；恢复（on_reconnect）时会再次校验上限。
口径是「全局」而非「每用户」：并发上限匹配 FunASR 房间总容量。
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.session import SessionStatus
from app.persistence.models import Base, InterviewRecord
from app.persistence.repositories.interview import InterviewRepository


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _add(db, sid: str, status: str, user_id: str = "u1") -> None:
    db.add(InterviewRecord(id=sid, template_id="t", status=status, user_id=user_id))
    await db.commit()


async def test_count_active_counts_only_live_and_is_global(db):
    """只数 setting_up/in_progress；suspended/created/ended 不数；跨用户全局合计。"""
    repo = InterviewRepository()
    await _add(db, "s1", SessionStatus.IN_PROGRESS.value, "u1")
    await _add(db, "s2", SessionStatus.SETTING_UP.value, "u2")  # 跨用户也算
    await _add(db, "s3", SessionStatus.SUSPENDED.value, "u1")   # 不数
    await _add(db, "s4", SessionStatus.CREATED.value, "u2")     # 不数
    await _add(db, "s5", SessionStatus.ENDED.value, "u1")       # 不数
    assert await repo.count_active(db) == 2


async def test_count_active_no_user_filter(db):
    """全局口径：不按 user_id 过滤。"""
    repo = InterviewRepository()
    await _add(db, "s1", SessionStatus.IN_PROGRESS.value, "u1")
    await _add(db, "s2", SessionStatus.IN_PROGRESS.value, "u2")
    assert await repo.count_active(db) == 2
