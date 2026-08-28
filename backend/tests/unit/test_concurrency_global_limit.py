"""全局并发上限（session.max_concurrent）+ SUSPENDED 不占名额 的行为校验。

回归点：用户暂停一场访谈后，应能新建并开始另一场（暂停态不再阻塞）；
同时「至多 N 场活跃」的护栏在 start 与 恢复（resume）两处都生效。
"""
from __future__ import annotations

import pytest

from app.core.exceptions import ConcurrentLimitError
from app.domain.session import SessionStatus
from app.services.sessions import manager as manager_module
from app.services.sessions.manager import SessionManager


class _FakeSession:
    def __init__(self, sid: str, status: SessionStatus) -> None:
        self.id = sid
        self.started_at = None
        self.status = status


class _FakeState:
    def __init__(self, sid: str, uid: str, status: SessionStatus) -> None:
        self.session = _FakeSession(sid, status)
        self.user_id = uid
        self.status = status


def _wire(mgr: SessionManager, monkeypatch, *, live: int, limit: int):
    """把 manager 的 DB/配置依赖替换为可控的同步桩。live=当前全局活跃数。"""

    async def _count():
        return live

    async def _save(state):  # noqa: ANN001
        return None

    async def _max_concurrent():
        return limit

    async def _transition(state, to):  # noqa: ANN001
        state.status = to
        state.session.status = to

    monkeypatch.setattr(manager_module.interview_repo, "count_active_auto", _count)
    monkeypatch.setattr(manager_module.interview_repo, "save_state_auto", _save)
    monkeypatch.setattr(manager_module, "get_max_concurrent", _max_concurrent)
    mgr._transition = _transition  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_suspended_does_not_block_new_start(monkeypatch):
    """已有暂停访谈（SUSPENDED 不计数）时，新访谈 start 不应被挡。"""
    mgr = SessionManager()
    new_state = _FakeState("new", "u1", SessionStatus.CREATED)

    async def _get(sid):  # noqa: ANN001
        return new_state

    mgr.get = _get  # type: ignore[assignment]
    # live=0：模拟「唯一的另一场是 SUSPENDED、不计数」
    _wire(mgr, monkeypatch, live=0, limit=4)

    res = await mgr.start("new")  # 不应抛 ConcurrentLimitError
    assert res.status == SessionStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_start_respects_global_limit(monkeypatch):
    """活跃数已达上限时，start 抛 ConcurrentLimitError；未达则成功。"""
    mgr = SessionManager()
    state = _FakeState("s", "u1", SessionStatus.CREATED)

    async def _get(sid):  # noqa: ANN001
        return state

    mgr.get = _get  # type: ignore[assignment]

    _wire(mgr, monkeypatch, live=4, limit=4)
    with pytest.raises(ConcurrentLimitError):
        await mgr.start("s")

    # 未达上限：成功
    _wire(mgr, monkeypatch, live=3, limit=4)
    res = await mgr.start("s")
    assert res.status == SessionStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_resume_blocked_when_at_limit(monkeypatch):
    """恢复 SUSPENDED 时若全局已达上限，应被挡（避免双活跃）。

    恢复入口是 manager.resume()（WS 重连不再自动转回 in_progress——避免网络
    抖动把列表状态刷成「进行中」；状态变更改由前端点「继续」触发 resume API）。
    并发上限校验随之落在 resume()，本测试守住这一护栏。
    """
    mgr = SessionManager()
    suspended = _FakeState("paused", "u1", SessionStatus.SUSPENDED)

    async def _get(sid):  # noqa: ANN001
        return suspended

    mgr.get = _get  # type: ignore[assignment]
    _wire(mgr, monkeypatch, live=4, limit=4)

    with pytest.raises(ConcurrentLimitError):
        await mgr.resume("paused")
    assert suspended.status == SessionStatus.SUSPENDED  # 未被转成 in_progress


@pytest.mark.asyncio
async def test_resume_ok_when_under_limit(monkeypatch):
    """恢复 SUSPENDED 时未达上限，应正常转回 in_progress。

    详见 test_resume_blocked_when_at_limit 头部说明。
    """
    mgr = SessionManager()
    suspended = _FakeState("paused", "u1", SessionStatus.SUSPENDED)

    async def _get(sid):  # noqa: ANN001
        return suspended

    mgr.get = _get  # type: ignore[assignment]
    _wire(mgr, monkeypatch, live=3, limit=4)

    res = await mgr.resume("paused")
    assert res.status == SessionStatus.IN_PROGRESS
