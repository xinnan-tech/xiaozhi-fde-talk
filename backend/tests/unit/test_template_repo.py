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


async def test_replace_with_expected_version_blocks_concurrent_writers(db):
    """乐观锁：expected_version 不匹配 → _OptimisticLockError，让 loader 转 409。

    两并发更新都读到 version=1、都写 version=2 时：第一个 OK，第二个被拒。
    """
    from app.persistence.repositories.template import _OptimisticLockError

    await template_repo.insert(db, _tpl())
    await db.commit()

    # 第一个写者：读到的版本是 "1"，写到 "2"
    await template_repo.replace(db, _tpl(name="v2"), version="2", expected_version="1")
    await db.commit()

    # 第二个写者：仍然以为自己读到的是 "1"，但库里已是 "2"
    with pytest.raises(_OptimisticLockError):
        await template_repo.replace(
            db, _tpl(name="v3"), version="2", expected_version="1",
        )
    await db.rollback()

    # 第二个写者改用 "2"（当前版本）→ 成功
    updated = await template_repo.replace(
        db, _tpl(name="v3"), version="3", expected_version="2",
    )
    await db.commit()
    assert updated.version == "3"
    assert updated.name == "v3"
