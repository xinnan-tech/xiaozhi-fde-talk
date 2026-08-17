"""first_batch_generated 标记：全量/收窄落盘都写、manager.update 清、寄存复用时刷新。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.runtime import RuntimeRegistry


@pytest.fixture
def mem_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)
    return engine, factory


async def _create(engine, factory):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return await manager.create("u-1", "pm-research", {"project": "P"}, "目标")


async def test_flag_roundtrip_full_and_coaching_save(mem_db):
    engine, factory = mem_db
    state = await _create(engine, factory)
    state.session.first_batch_generated = True
    await interview_repo.save_state_auto(state)  # 全量写
    loaded = await interview_repo.get_state_auto(state.session.id)
    assert loaded.session.first_batch_generated is True

    state.session.first_batch_generated = False
    await interview_repo.save_state_auto(state, fields={"coaching"})  # 收窄写也带 flag
    loaded = await interview_repo.get_state_auto(state.session.id)
    assert loaded.session.first_batch_generated is False


async def test_update_clears_flag_only_on_real_change(mem_db):
    engine, factory = mem_db
    state = await _create(engine, factory)  # goal="目标"
    state.session.first_batch_generated = True
    await interview_repo.save_state_auto(state)
    await manager.update(state.session.id, None, "目标")  # 等值编辑：goal 原值重发
    loaded = await manager.get(state.session.id)  # created 不在 _active，从 DB 载入
    assert loaded.session.first_batch_generated is True
    await manager.update(state.session.id, {"project": "X"}, None)  # 实际变更
    loaded = await manager.get(state.session.id)
    assert loaded.session.first_batch_generated is False


def test_refresh_session_fields_copies_flag(make_state):
    rt_state = make_state()
    rt_state.session.first_batch_generated = True
    fresh = rt_state.session.model_copy(
        update={"goal": "新目标", "first_batch_generated": False}
    )
    RuntimeRegistry._refresh_session_fields(SimpleNamespace(state=rt_state), fresh)
    assert rt_state.session.first_batch_generated is False
