"""P2-13 · save_state 会话级写串行锁。

manager 定时器（_grace_expire / _suspend_idle）与 runtime flush 会并发对同一
session 调 save_state_auto（各自开独立 SessionLocal 连接/事务）。SQLite 下并发写
触发 'database is locked'；事务交错也让分组写（P2-8c fields）半新半旧。共享
SessionState 下无真正 lost update，加 per-session Lock 串行化 DB 写即可，不 raise。
"""
from __future__ import annotations

import asyncio

import pytest

from app.domain.session import Session
from app.domain.session_state import SessionState
from app.persistence.repositories.interview import InterviewRepository
from app.services.template.loader import get_template


def _make_state(sid: str) -> SessionState:
    tpl = get_template("pm-research")
    session = Session(id=sid, template_id="pm-research", goal="g", status="in_progress")
    return SessionState.initial(session, tpl)


class _Rec:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.status = "in_progress"


class _SlowFakeSession:
    """记录 get/commit 顺序并在其间 yield，使并发交错可观测。"""

    def __init__(self, record, events: list) -> None:
        self._record = record
        self._events = events

    async def get(self, cls, pk):  # noqa: ARG002
        self._events.append(("get", pk))
        await asyncio.sleep(0)  # yield — 让另一协程有机会插入
        return self._record

    def add(self, obj) -> None:
        self._record = obj

    async def commit(self) -> None:
        self._events.append(("commit",))
        await asyncio.sleep(0)


def _idx(events, kind):
    return [i for i, e in enumerate(events) if e[0] == kind]


@pytest.mark.asyncio
async def test_concurrent_save_state_same_session_serialized():
    """同 session 并发 save：第二个 get 必在第一个 commit 之后（串行，无交错）。"""
    state = _make_state("s-serial")
    repo = InterviewRepository()
    events: list = []

    await asyncio.gather(
        repo.save_state(_SlowFakeSession(_Rec(state.session.id), events), state),
        repo.save_state(_SlowFakeSession(_Rec(state.session.id), events), state),
    )

    get_idx = _idx(events, "get")
    commit_idx = _idx(events, "commit")
    assert len(get_idx) == 2 and len(commit_idx) == 2
    assert commit_idx[0] < get_idx[1], (
        f"并发 save_state 未串行化，事务交错：{events}"
    )


@pytest.mark.asyncio
async def test_different_sessions_not_blocked():
    """不同 session 的 save 不互相阻塞（per-session 粒度，非全局锁）。"""
    repo = InterviewRepository()
    events: list = []

    await asyncio.gather(
        repo.save_state(_SlowFakeSession(_Rec("sess-a"), events), _make_state("sess-a")),
        repo.save_state(_SlowFakeSession(_Rec("sess-b"), events), _make_state("sess-b")),
    )

    get_idx = _idx(events, "get")
    commit_idx = _idx(events, "commit")
    # 不同 session → 允许交错：两个 get 都在首个 commit 前
    assert get_idx[1] < commit_idx[0], (
        f"不同 session 的 save 不应串行（误用全局锁？）：{events}"
    )
