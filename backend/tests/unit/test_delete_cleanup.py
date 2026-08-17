"""删除访谈的关联清理回归测试。

manager.delete 须先拆除 registry 中寄存的运行时，再删 DB 行——否则寄存 runtime 的
存活窗口到期会跑 runtime.end() → save_state（记录缺失时重建行），把已删访谈「复活」
成僵尸行。grace 挂起态删除尤其易触发：registry 仍寄存着 runtime，而 delete 守卫放行。
"""
from __future__ import annotations

import pytest

from app.domain.session import Session, SessionStatus
from app.services.sessions import manager as manager_mod
from app.services.sessions.manager import SessionManager
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


class _FakeRuntime:
    def __init__(self) -> None:
        self.ended = False

    async def end(self) -> None:
        self.ended = True


class _FakeRegistry:
    """记录 get/drop；get 返回注入的 runtime（或 None）。"""

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self.dropped: str | None = None

    def get(self, session_id: str):  # noqa: ARG002
        return self._runtime

    def drop(self, session_id: str) -> None:
        self.dropped = session_id


def _patch_deps(monkeypatch, runtime):
    """替 manager 注入假 registry 与假 repo.delete_auto，返回收集结果的字典。"""
    monkeypatch.setattr(manager_mod, "registry", _FakeRegistry(runtime))
    deleted: dict = {}

    async def _fake_delete_auto(session_id: str) -> bool:
        deleted["sid"] = session_id
        return True

    monkeypatch.setattr(manager_mod.interview_repo, "delete_auto", _fake_delete_auto)
    return deleted


@pytest.mark.asyncio
async def test_delete_tears_down_parked_runtime(monkeypatch):
    """挂起态删除：须先 drop 存活定时器、再 end() 运行时，最后删 DB 行。"""
    runtime = _FakeRuntime()
    deleted = _patch_deps(monkeypatch, runtime)

    tpl = get_template("pm-research")
    state = SessionState.initial(
        Session(id="s-del", template_id="pm-research", status=SessionStatus.SUSPENDED),
        tpl,
    )
    mgr = SessionManager()
    mgr._active["s-del"] = state  # 让 self.get 不走 DB

    await mgr.delete("s-del")

    assert manager_mod.registry.dropped == "s-del", "删除须 registry.drop 取消存活窗口定时器"
    assert runtime.ended, "删除须 runtime.end() 释放 ASR/管线，杜绝过期复活"
    assert deleted.get("sid") == "s-del", "删除仍须删 DB 行"


@pytest.mark.asyncio
async def test_delete_without_runtime_still_works(monkeypatch):
    """无寄存运行时（从未开始 / 已结束）时删除不应报错，仍正常 drop + 删行。"""
    deleted = _patch_deps(monkeypatch, runtime=None)

    tpl = get_template("pm-research")
    state = SessionState.initial(
        Session(id="s-none", template_id="pm-research", status=SessionStatus.CREATED),
        tpl,
    )
    mgr = SessionManager()
    mgr._active["s-none"] = state

    await mgr.delete("s-none")

    assert manager_mod.registry.dropped == "s-none"
    assert deleted.get("sid") == "s-none"
