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
        session={"goal": "", "base_fields": [
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


# === P2 _bump_version 校验（#2 / #8） ===

def test_bump_version_happy_path():
    """合法数字字符串 +1。"""
    from app.services.template.loader import _bump_version

    assert _bump_version("1") == "2"
    assert _bump_version("99") == "100"


def test_bump_version_rejects_non_numeric():
    """非法字符串抛 I18nError 422（旧实现是静默回退到 "1"，会触发乐观锁恒真）。"""
    from app.core.i18n.errors import I18nError

    from app.services.template.loader import _bump_version

    for bad in ["", "abc", "v2", "1.0", "0"]:
        try:
            _bump_version(bad)
        except I18nError as e:
            assert e.http_status == 422
            assert "version" in str(e).lower() or "version" in str(e.code).lower()
        else:
            raise AssertionError(f"_bump_version({bad!r}) should have raised")

    # 负数：int("-1")=-1 不抛 ValueError，但 n<1 也得拒
    try:
        _bump_version("-1")
    except I18nError as e:
        assert e.http_status == 422
    else:
        raise AssertionError("_bump_version('-1') should have raised")


def test_bump_version_rejects_overflow():
    """+1 后超 14 位（DB String(16) 留 2 位余量）抛 422。

    上限 14 位来自 DB String(16) 列宽：14 位数字 = 10^14-1，+1 后 15 位
    仍 ≤ 16；再大就被拒，让用户在版本号耗尽前收到清晰错误
    （旧版静默写到 DB 才报错的情况）。
    """
    from app.core.i18n.errors import I18nError

    from app.services.template.loader import _bump_version

    # 13 位最大（9999999999999 = 10^13-1）+ 1 = 10000000000000（14 位）→ 合法
    assert _bump_version("9" * 13) == "1" + "0" * 13

    # 14 位（99999999999999 = 10^14-1）+ 1 = 100000000000000（15 位 > 14 上限）→ 拒
    with pytest.raises(I18nError) as exc:
        _bump_version("9" * 14)
    assert exc.value.http_status == 422

    # 15 位起更大也直接拒
    with pytest.raises(I18nError):
        _bump_version("9" * 15)
