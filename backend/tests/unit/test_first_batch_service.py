"""first_batch.generate_first_batch：无 runtime 路径——生成落盘、幂等、并发不双算、锁回收。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.services.coaching import first_batch as fb

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.coaching.first_batch import generate_first_batch
from app.services.sessions.manager import manager


@pytest.fixture
def mem_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)
    return engine, factory


def _llm_mock(monkeypatch):
    llm = AsyncMock()
    llm.chat_json.return_value = {"items": [
        {"id": "objective", "text": "定制目标问题", "status": "todo"},
    ]}
    monkeypatch.setattr("app.services.coaching.engine.get_llm", lambda: llm)
    return llm


async def test_generate_persists_and_idempotent(mem_db, monkeypatch):
    engine, factory = mem_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    llm = _llm_mock(monkeypatch)
    state = await manager.create("u-1", "pm-research", {"project": "P"}, "目标")
    result = await generate_first_batch(state.session.id)
    assert result.session.first_batch_generated is True
    assert llm.chat_json.await_count == 1

    result2 = await generate_first_batch(state.session.id)  # 第二次幂等
    assert result2.session.first_batch_generated is True
    assert llm.chat_json.await_count == 1
    reloaded = await manager.get(state.session.id)
    assert reloaded.session.first_batch_generated is True
    assert state.session.id not in fb._inflight  # 锁用完回收，不泄漏


async def test_generate_concurrent_single_llm_call(mem_db, monkeypatch):
    """并发双 POST：in-flight 锁内重载复查，只算一次。"""
    engine, factory = mem_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    llm = _llm_mock(monkeypatch)
    payload = {"items": [
        {"id": "objective", "text": "定制目标问题", "status": "todo"},
    ]}

    async def slow(*a, **k):
        await asyncio.sleep(0.05)  # 拉开重叠窗口：无锁防御时两个请求都会调 LLM
        return payload

    llm.chat_json.side_effect = slow
    state = await manager.create("u-1", "pm-research", {"project": "P"}, "目标")
    r1, r2 = await asyncio.gather(
        generate_first_batch(state.session.id),
        generate_first_batch(state.session.id),
    )
    assert llm.chat_json.await_count == 1
    assert r1.session.first_batch_generated is True
    assert r2.session.first_batch_generated is True


async def test_generate_missing_session(mem_db, monkeypatch):
    engine, factory = mem_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _llm_mock(monkeypatch)
    assert await generate_first_batch("no-such") is None


async def test_generate_does_not_resurrect_deleted_session(mem_db, monkeypatch):
    """LLM 调用窗口内会话被删 → 落盘不得把已删行复活成僵尸。"""
    engine, factory = mem_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    llm = _llm_mock(monkeypatch)
    payload = {"items": [
        {"id": "objective", "text": "定制目标问题", "status": "todo"},
    ]}

    async def slow(*a, **k):
        await asyncio.sleep(0.05)  # 拉开窗口：delete 须落在 LLM 与落盘之间
        return payload

    llm.chat_json.side_effect = slow
    state = await manager.create("u-1", "pm-research", {"project": "P"}, "目标")
    sid = state.session.id

    async def delete_later():
        await asyncio.sleep(0.02)  # 等 generate 已进入 LLM 调用窗口
        await manager.delete(sid)

    await asyncio.gather(generate_first_batch(sid), delete_later())
    assert await interview_repo.get_session_auto(sid) is None  # 行没复活
