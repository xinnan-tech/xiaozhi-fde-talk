"""· ReportRecord.interview_id 加 FK CASCADE + unique。

原 interview_id 仅 String(36) index=True，无外键约束、无唯一约束：
- 删 interview 后 report 成孤儿（无 CASCADE 清理）
- 同一 interview 可有多条 report（业务上一次访谈一份报告）
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.db import _enable_sqlite_foreign_keys
from app.persistence.models import Base, InterviewRecord, ReportRecord


def _col(name: str):
    return ReportRecord.__table__.columns[name]


def test_report_interview_id_has_fk_cascade():
    col = _col("interview_id")
    fks = list(col.foreign_keys)
    assert fks, "interview_id 应有外键约束"
    fk = fks[0]
    assert fk.ondelete == "CASCADE", f"ondelete 应为 CASCADE，got {fk.ondelete!r}"
    assert fk.column.table.name == "interviews"
    assert fk.column.name == "id"


def test_report_interview_id_is_unique():
    col = _col("interview_id")
    assert col.unique is True, "interview_id 应 unique（一次访谈一份报告）"


def test_report_interview_id_still_indexed():
    col = _col("interview_id")
    assert col.index is True, "interview_id 应保留索引"


@pytest.mark.asyncio
async def test_delete_interview_cascades_report_at_runtime():
    """PRAGMA foreign_keys=ON 使 ondelete=CASCADE 在运行时真正生效：删访谈级联删报告。

    回归：metadata 层声明 CASCADE 不够——SQLite 默认不强制外键，引擎须显式开
    PRAGMA。曾经因此删访谈后报告成为孤儿（上面的元数据断言测不出这点）。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _enable_sqlite_foreign_keys(engine)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as db:
            db.add(InterviewRecord(id="iv-1", template_id="tpl-1"))
            await db.commit()
        async with Session() as db:
            db.add(ReportRecord(id="rp-1", interview_id="iv-1"))
            await db.commit()

        async with Session() as db:
            await db.delete(await db.get(InterviewRecord, "iv-1"))
            await db.commit()

        async with Session() as db:
            orphan = await db.get(ReportRecord, "rp-1")
        assert orphan is None, "删访谈应级联删除其报告，不应残留孤儿"
    finally:
        await engine.dispose()
