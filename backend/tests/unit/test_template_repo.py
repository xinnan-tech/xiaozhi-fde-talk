"""TemplateRepository CRUD + 引用计数（内存 SQLite，离线）。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.template import Template
from app.persistence.models import Base, InterviewRecord, TemplateRecord
from app.persistence.repositories.template import template_repo


def _tpl(tid: str = "fde-demo", name: str = "FDE 演示") -> Template:
    return Template(
        id=tid, name=name, icon_alt="🧪", version="1",
        session={"name": "演示", "goal": "", "base_fields": [
            {"key": "project", "label": "项目"},
        ], "setup": {"intro": "", "extract_to": [], "required": []}},
        coaching={"playbook": "", "must_ask": [
            {"id": "q1", "text": "问什么"},
        ]},
        report={"doc": "# {{session.project}}\n"},
    )


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            TemplateRecord.__table__, InterviewRecord.__table__,
        ])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_insert_and_get_roundtrip(db):
    rec = await template_repo.insert(db, _tpl())
    await db.commit()
    got = await template_repo.get(db, "fde-demo")
    assert got is not None
    assert got.name == "FDE 演示"
    # content 是真相源：完整结构可反序列化回 domain 模型
    assert Template(**got.content).coaching.must_ask[0].id == "q1"
    assert rec.content["report"]["doc"].startswith("# {{session.project}}")


async def test_replace_bumps_written_version(db):
    await template_repo.insert(db, _tpl())
    await db.commit()
    tpl2 = _tpl(name="FDE 演示 v2")
    await template_repo.replace(db, tpl2, version="7")
    await db.commit()
    got = await template_repo.get(db, "fde-demo")
    assert got.name == "FDE 演示 v2"
    assert got.version == "7"
    assert got.updated_at is not None


async def test_delete_missing_returns_false(db):
    assert await template_repo.delete(db, "nope") is False


async def test_count_interviews(db):
    await template_repo.insert(db, _tpl())
    db.add_all([
        InterviewRecord(id="i1", template_id="fde-demo", status="ended"),
        InterviewRecord(id="i2", template_id="fde-demo", status="created"),
        InterviewRecord(id="i3", template_id="other", status="ended"),
    ])
    await db.commit()
    assert await template_repo.count_interviews(db, "fde-demo") == 2
    grouped = await template_repo.count_interviews_grouped(db)
    assert grouped == {"fde-demo": 2, "other": 1}
