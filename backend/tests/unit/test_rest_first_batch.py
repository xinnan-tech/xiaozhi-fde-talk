"""POST /interviews/{id}/first-batch：预热首评——幂等、归属 404、结束态跳过、走 runtime 引擎；
PATCH 实际变更清 flag → 断连寄存 → 重连刷新 → snapshot 后台重生成。"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.i18n.errors import I18nError
from app.core.policies import get_policy
from app.domain.auth import CurrentUser
from app.domain.session import SessionStatus
from app.persistence.models import Base
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.transport.http.routes.interviews import first_batch_interview, get_interview


@pytest.fixture
def mem_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)
    return engine, factory


async def _create(mem_db):
    engine, factory = mem_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    state = await manager.create("u-1", "pm-research", {"project": "P"}, "目标")
    return state


def _llm_mock(monkeypatch):
    llm = AsyncMock()
    llm.chat_text.return_value = '{"items": [{"id": "objective", "text": "定制目标问题", "status": "todo"}]}'
    monkeypatch.setattr("app.services.coaching.engine.get_llm", lambda: llm)
    return llm


async def test_first_batch_generates_once_then_idempotent(mem_db, monkeypatch):
    state = await _create(mem_db)
    llm = _llm_mock(monkeypatch)
    user = CurrentUser(user_id="u-1", username="t")

    r1 = await first_batch_interview(state.session.id, user)
    assert r1["generated"] is True and len(r1["items"]) == 1
    r2 = await first_batch_interview(state.session.id, user)
    assert r2["generated"] is True
    assert llm.chat_text.await_count == 1


async def test_first_batch_other_user_404(mem_db, monkeypatch):
    state = await _create(mem_db)
    _llm_mock(monkeypatch)
    intruder = CurrentUser(user_id="u-2", username="t")
    with pytest.raises(I18nError) as e:
        await first_batch_interview(state.session.id, intruder)
    assert e.value.http_status == 404


async def test_first_batch_ended_session_skips_llm(mem_db, monkeypatch):
    state = await _create(mem_db)
    await manager.end(state.session.id)
    llm = _llm_mock(monkeypatch)
    user = CurrentUser(user_id="u-1", username="t")
    r = await first_batch_interview(state.session.id, user)
    assert r["generated"] is False
    llm.chat_text.assert_not_awaited()


async def test_first_batch_routes_through_runtime_engine(mem_db, monkeypatch):
    state = await _create(mem_db)
    await manager.start(state.session.id)
    fresh = await manager.get(state.session.id)
    rt = registry.get_or_create(state.session.id, fresh, get_policy("ws"))
    try:
        rt.ainit()
        llm = _llm_mock(monkeypatch)
        user = CurrentUser(user_id="u-1", username="t")
        r = await first_batch_interview(state.session.id, user)
        assert r["generated"] is True
        assert llm.chat_text.await_count == 1
        assert rt.state.session.first_batch_generated is True  # runtime 的 state 对象被更新
    finally:
        registry.drop(state.session.id)


async def test_detail_includes_flag(mem_db):
    state = await _create(mem_db)
    user = CurrentUser(user_id="u-1", username="t")
    d = await get_interview(state.session.id, user)
    assert d["first_batch_generated"] is False


async def test_patch_park_reconnect_regenerates(mem_db, monkeypatch, wait_for_tasks):
    """真实链路：首绑生成 → 断连寄存 → 寄存期间 PATCH 实际变更清 flag →
    重连 get_or_create 刷新快照 → bind snapshot 补跑首评（LLM 定制清单回 DB）。"""
    state = await _create(mem_db)
    sid = state.session.id
    llm = _llm_mock(monkeypatch)

    sent = []

    async def send(msg):
        sent.append(msg)

    rt = registry.get_or_create(sid, await manager.get(sid), get_policy("ws"))
    try:
        rt.ainit()
        await rt.bind(send, client_id="c1")  # 首绑：首算 + 后台首评
        await wait_for_tasks()
        assert rt.state.session.first_batch_generated is True
        assert llm.chat_text.await_count == 1

        await rt.unbind(send)  # 断连：拆绑（强制落盘）→ 寄存
        registry.park(sid, rt, ttl_s=60)

        await manager.update(sid, {"project": "X"}, None)  # 真实 PATCH：实际变更清 flag 落 DB
        assert (await manager.get(sid)).session.first_batch_generated is False

        rt2 = registry.get_or_create(sid, await manager.get(sid), get_policy("ws"))
        assert rt2 is rt  # 寄存窗口内取回同一 runtime，快照已刷成 DB 现值
        assert rt2.state.session.first_batch_generated is False
        rt2.ainit()
        await rt2.bind(send, client_id="c1")  # 重连 bind：snapshot → 后台补跑首评
        await wait_for_tasks()

        assert rt2.state.session.first_batch_generated is True
        assert llm.chat_text.await_count == 2
        assert [it.text for it in rt2.state.items] == ["定制目标问题"]  # LLM 定制，非模板 6 条种子
        assert (await manager.get(sid)).session.first_batch_generated is True  # 已回写 DB
    finally:
        registry.drop(sid)
