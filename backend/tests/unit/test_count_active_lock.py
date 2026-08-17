"""全局并发上限的 TOCTOU 串行化：单把 _start_lock 守 count_active→save 临界区。

并发口径是「全局」（匹配 FunASR 房间总容量），因此不同用户的并发 start 也必须
串行——否则 u1/u2 同时 start 都读到 active=0、都过限流、都落盘 → 超过房间数。

判定：count_active 做成「立即读全局活跃集长度（不挂起）」，_transition 做成
「改状态后 await asyncio.sleep(0)」（在读与写之间插入真实挂起点，放大 TOCTOU）。
- 无锁：两 start 都读到 0 → 都过限流 → 都 save → 0 个 ConcurrentLimitError（红）
- 有全局锁：先者 save 后，后者 count 看到 1 → 抛 ConcurrentLimitError（绿）

确定性：count/get 是无内部 await 的 async def（内联返回，不让出循环），唯一挂起点
是 _transition 的 sleep(0)，因此调度顺序可控、无计时竞态。
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import ConcurrentLimitError
from app.domain.session import SessionStatus
from app.services.sessions import manager as manager_module
from app.services.sessions.manager import SessionManager


class _FakeSession:
    def __init__(self, sid: str) -> None:
        self.id = sid
        self.started_at = None


class _FakeState:
    def __init__(self, sid: str, uid: str) -> None:
        self.session = _FakeSession(sid)
        self.user_id = uid
        self.status = SessionStatus.CREATED


@pytest.mark.asyncio
async def test_concurrent_start_serialized_globally(monkeypatch):
    """不同用户并发 start：恰好一个成功、一个 ConcurrentLimitError（全局锁）。"""
    mgr = SessionManager()
    # 关键：两场会话分属不同用户，证明串行化是全局的、非 per-user。
    state_a = _FakeState("sess-a", "u1")
    state_b = _FakeState("sess-b", "u2")
    states = {"sess-a": state_a, "sess-b": state_b}

    async def _get_state(sid):
        return states[sid]

    mgr.get = _get_state  # type: ignore[assignment]

    async def _transition(state, to):  # noqa: ANN001
        state.status = to
        await asyncio.sleep(0)  # 在 count 读与 save 写之间插入真实挂起点

    mgr._transition = _transition  # type: ignore[assignment]

    live: set[str] = set()  # 全局活跃集

    async def _count():  # 无参数：全局口径
        return len(live)

    async def _save(state):  # noqa: ANN001
        live.add(state.session.id)

    async def _max_concurrent():
        return 1  # 全局只允许 1 场活跃

    monkeypatch.setattr(manager_module.interview_repo, "count_active_auto", _count)
    monkeypatch.setattr(manager_module.interview_repo, "save_state_auto", _save)
    monkeypatch.setattr(manager_module, "get_max_concurrent", _max_concurrent)

    results = await asyncio.gather(
        mgr.start("sess-a"), mgr.start("sess-b"), return_exceptions=True
    )

    raises = [r for r in results if isinstance(r, ConcurrentLimitError)]
    assert len(raises) == 1, (
        f"期望恰好 1 个 ConcurrentLimitError（全局锁串行化），"
        f"实际 {len(raises)}：{[type(r).__name__ for r in results]}"
    )
    assert len(live) == 1, "只应有一场会话成功落盘为活跃"


def test_start_lock_is_single_global_lock():
    """manager 应持有一把全局 _start_lock（非 per-user 字典）。"""
    mgr = SessionManager()
    assert hasattr(mgr, "_start_lock"), "manager 缺 _start_lock"
    assert isinstance(mgr._start_lock, asyncio.Lock)
