from __future__ import annotations

import inspect


async def test_runtime_methods_call_manager_touch(make_state, monkeypatch):
    """入站方法触达后经 _touch 调用 manager.touch，更新会话活跃度。

    _touch 在 runtime 内延迟导入 manager，规避与 manager.py 的循环依赖
    （manager.py 顶部从 runtime 导入 registry，故 runtime 不能在顶部反向导入 manager）。
    """
    from app.services.sessions import manager as mgr_mod
    from app.services.sessions.runtime import SessionRuntime

    rt = SessionRuntime(make_state())
    touched: list[str] = []
    monkeypatch.setattr(mgr_mod.manager, "touch", lambda sid: touched.append(sid))

    await rt.skip(None)     # item_id=None → 仅 touch，不落库
    await rt.ignore(None)   # 同上

    sid = rt.state.session.id
    assert touched == [sid, sid]


def test_no_bare_manager_touch_in_runtime():
    """runtime 方法体内不得残留裸 manager.touch(self.state.session.id) —— 一律经 _touch 收口。"""
    import app.services.sessions.runtime as rt_mod

    src = inspect.getsource(rt_mod)
    assert "manager.touch(self.state.session.id)" not in src
