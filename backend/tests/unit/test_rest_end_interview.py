"""POST /interviews/{id}/end：结束访谈的唯一入口。

结束不走 WS 帧（会话状态归 HTTP 管，WS 只承载音频/转写）。契约：
- manager.end 先把 ENDED 落盘再返回，列表即时可见；
- runtime 收尾（coaching 终算 LLM，超时上限 60s）放后台任务，不阻塞请求。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.domain.session import SessionStatus
from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.transport.http.routes.interviews import end_interview


@pytest.fixture
def mem_db(monkeypatch):
    """内存库，并把 repo / config_store 的 SessionLocal 都指过去。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)
    return engine, factory


async def _mk_in_progress(factory):
    async with factory() as db:
        pass  # create_all 由调用方在 engine 上完成
    user = CurrentUser(user_id="u-1", username="t")
    state = await manager.create(user.user_id, "pm-research", {}, "目标")
    await manager.start(state.session.id)
    return user, state.session.id


async def test_end_interview_persists_ended(mem_db):
    engine, factory = mem_db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        user, sid = await _mk_in_progress(factory)

        resp = await end_interview(sid, user)
        assert resp["status"] == "ended"

        saved = await interview_repo.get_state_auto(sid)
        assert saved.session.status is SessionStatus.ENDED
        assert saved.session.ended_at is not None
    finally:
        await engine.dispose()


async def test_end_interview_not_found(mem_db):
    engine, _ = mem_db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        user = CurrentUser(user_id="u-1", username="t")
        with pytest.raises(I18nError) as ei:
            await end_interview("no-such-session", user)
        assert ei.value.http_status == 404
    finally:
        await engine.dispose()


async def test_end_returns_before_slow_runtime_teardown(mem_db, monkeypatch):
    """收尾 LLM 阻塞时请求照常返回（ENDED 已落盘），收尾在后台跑。"""
    engine, factory = mem_db
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        user, sid = await _mk_in_progress(factory)

        runtime_started = asyncio.Event()
        release = asyncio.Event()

        async def slow_teardown():
            runtime_started.set()
            await release.wait()  # 模拟 coaching 终算 LLM 阻塞

        fake_rt = MagicMock()
        fake_rt.end = AsyncMock(side_effect=slow_teardown)
        monkeypatch.setattr(registry, "get", lambda session_id: fake_rt)

        resp = await end_interview(sid, user)
        assert resp["status"] == "ended", "结束请求被 runtime 收尾（LLM）阻塞了"

        saved = await interview_repo.get_state_auto(sid)
        assert saved.session.status is SessionStatus.ENDED

        await runtime_started.wait()  # 收尾确实已调度
        release.set()
        await asyncio.sleep(0.05)  # 让后台任务跑完，不留 pending task
    finally:
        await engine.dispose()
