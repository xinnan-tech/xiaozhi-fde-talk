"""dev DB 自愈：create_all 之后的缺列 ALTER。

回归需求：
- 现有 reports 表缺 transcript_signature / output_language → ADD COLUMN 补上
- 已有这些列 → 跳过（idempotent）
- 多调用一次也不报错
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.persistence.bootstrap import _column_exists, _ensure_columns, _SELF_HEAL_COLUMNS


@pytest.fixture
async def fake_old_db_engine():
    """造一个缺自愈列的老 dev DB：reports 缺 transcript_signature 与 output_language、interviews 缺 first_batch_generated。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 对应 ORM 模型之外的最小字段集（不引入 Base.metadata，避免新表自带列）
        await conn.execute(text(
            "CREATE TABLE reports ("
            "  id VARCHAR(36) PRIMARY KEY,"
            "  interview_id VARCHAR(36) NOT NULL,"
            "  content_md TEXT DEFAULT '',"
            "  status VARCHAR(32) DEFAULT 'pending',"
            "  skill_outputs JSON DEFAULT '{}'"
            ")"
        ))
        await conn.execute(text(
            "CREATE TABLE interviews ("
            "  id VARCHAR(36) PRIMARY KEY,"
            "  template_id VARCHAR(64),"
            "  status VARCHAR(32),"
            "  goal TEXT"
            ")"
        ))
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_column_exists_false_before_heal(fake_old_db_engine):
    """工厂确认：缺 transcript_signature。"""
    async with fake_old_db_engine.connect() as conn:
        assert await _column_exists(conn, "reports", "transcript_signature") is False


@pytest.mark.asyncio
async def test_ensure_columns_adds_missing(fake_old_db_engine):
    """缺列 → ADD COLUMN。"""
    async with fake_old_db_engine.begin() as conn:
        await _ensure_columns(conn)
        assert await _column_exists(conn, "reports", "transcript_signature") is True
        assert await _column_exists(conn, "reports", "output_language") is True
        assert await _column_exists(conn, "interviews", "first_batch_generated") is True


@pytest.mark.asyncio
async def test_ensure_columns_idempotent(fake_old_db_engine):
    """跑两次不报错、不重复 ALTER。"""
    async with fake_old_db_engine.begin() as conn:
        await _ensure_columns(conn)
        await _ensure_columns(conn)
        assert await _column_exists(conn, "reports", "transcript_signature") is True


@pytest.mark.asyncio
async def test_ensure_columns_uses_ddl_with_default(fake_old_db_engine):
    """DEFAULT '' 落实：老行 SELECT 出来是空串而不是 NULL。"""
    async with fake_old_db_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO reports (id, interview_id) VALUES ('r1', 'i1')"
        ))
        await conn.execute(text(
            "INSERT INTO interviews (id, template_id, status, goal) VALUES ('i1', 't', 'created', 'g')"
        ))
        await _ensure_columns(conn)
        row = (await conn.execute(text(
            "SELECT transcript_signature FROM reports WHERE id='r1'"
        ))).one()
        assert row[0] == ""
        # output_language 也需 DEFAULT '' 落实
        row2 = (await conn.execute(text(
            "SELECT output_language FROM reports WHERE id='r1'"
        ))).one()
        assert row2[0] == ""
        irow = (await conn.execute(text(
            "SELECT first_batch_generated FROM interviews WHERE id='i1'"
        ))).one()
        assert irow[0] == 0  # BOOLEAN DEFAULT 0：老行读出 0 而非 NULL（==0 才能区分 None）


@pytest.mark.asyncio
async def test_ensure_columns_handles_full_real_schema(fake_old_db_engine):
    """真实 Base.metadata.create_all 跑出来的完整表（已含 transcript_signature）→ 跳过。"""
    from app.persistence.models import Base

    async with fake_old_db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 第一次：刚 create_all 出来，列已存在 → noop
        await _ensure_columns(conn)
        # 列表里每个 (table, column) 都该已存在
        for table, column, _ddl in _SELF_HEAL_COLUMNS:
            assert await _column_exists(conn, table, column) is True
