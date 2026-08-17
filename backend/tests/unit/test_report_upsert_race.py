"""报告 upsert 并发竞态回归。

同一 interview 的两次并发首次生成（如双端同时点「查看报告」），旧
get-then-insert 会双读 None、双 insert，后者 commit 撞 interview_id
唯一索引 → 500。方言级 upsert 后应始终恰好一条且值是最后写入的。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.db import _enable_sqlite_foreign_keys
from app.persistence.models import Base, InterviewRecord, ReportRecord
from app.persistence.repositories.report import report_repo


async def _make_engine_with_interview(iv_id: str):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add(InterviewRecord(id=iv_id, template_id="tpl-1"))
        await db.commit()
    return engine, Session


@pytest.mark.asyncio
async def test_concurrent_upserts_single_row_no_unique_violation():
    engine, Session = await _make_engine_with_interview("iv-1")
    try:
        async def _upsert(content: str) -> None:
            async with Session() as db:
                await report_repo.upsert(
                    db, "iv-1", content_md=content, status="ready",
                    transcript_signature="sig-" + content,
                )

        await asyncio.gather(_upsert("A"), _upsert("B"), _upsert("C"))

        async with Session() as db:
            count = (await db.execute(
                select(func.count()).select_from(ReportRecord.__table__)
            )).scalar_one()
        assert count == 1, f"并发生成应恰好落一条报告，got {count}"

        async with Session() as db:
            rec = await report_repo.get_by_interview(db, "iv-1")
        # 三个写者的落定顺序不定，但值必须三选一且与签名一致（同事务字段不分裂）
        assert rec.content_md in {"A", "B", "C"}
        assert rec.transcript_signature == "sig-" + rec.content_md
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_overwrites_existing_row():
    engine, Session = await _make_engine_with_interview("iv-2")
    try:
        async with Session() as db:
            await report_repo.upsert(db, "iv-2", "旧报告", "ready", "s1")
        async with Session() as db:
            await report_repo.upsert(db, "iv-2", "新报告", "ready", "s2")

        async with Session() as db:
            rec = await report_repo.get_by_interview(db, "iv-2")
            count = (await db.execute(
                select(func.count()).select_from(ReportRecord.__table__)
            )).scalar_one()
        assert rec.content_md == "新报告"
        assert rec.transcript_signature == "s2"
        assert count == 1, "更新不应新增行"
    finally:
        await engine.dispose()
