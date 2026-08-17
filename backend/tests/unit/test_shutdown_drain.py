from __future__ import annotations

from unittest.mock import AsyncMock

from app.services.sessions.runtime import RuntimeRegistry, SessionRuntime


async def test_shutdown_quick_closes_pipeline_no_llm(make_state):
    rt = SessionRuntime(make_state())
    rt.pipeline.close = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_end = AsyncMock()  # shutdown_quick 不应调 on_end（不等 LLM）
    await rt.shutdown_quick()
    rt.pipeline.close.assert_awaited()
    rt._save_state.assert_awaited()
    rt.engine.on_end.assert_not_awaited()


async def test_registry_all_runtimes_lists_parked(make_state):
    reg = RuntimeRegistry()
    rt = SessionRuntime(make_state())
    reg.park("s1", rt, ttl_s=100)
    assert rt in reg.all_runtimes()
    reg.drop("s1")  # 取消 100s expire 任务，避免 dangling-task 告警


async def test_shutdown_quick_marks_suspended_for_resume(make_state):
    """进程关停：WS 随进程死亡，落盘 suspended 以便重启后可继续。

    shutdown_quick 主动转 suspended，不写 ended（用户没主动结束，仍应能继续访谈）；
    若落盘 in_progress，重启后状态会卡进行中。
    """
    from app.domain.session import SessionStatus

    rt = SessionRuntime(make_state())              # status = in_progress
    rt.pipeline.close = AsyncMock()
    rt._save_state = AsyncMock()
    await rt.shutdown_quick()
    assert rt.state.session.status is SessionStatus.SUSPENDED
    rt._save_state.assert_awaited()                # 转换后落盘


async def test_shutdown_quick_keeps_ended_as_is(make_state):
    """已结束的会话关停时不被回写成 suspended。"""
    from app.domain.session import SessionStatus

    rt = SessionRuntime(make_state())
    rt.state.session.status = SessionStatus.ENDED
    rt.pipeline.close = AsyncMock()
    rt._save_state = AsyncMock()
    await rt.shutdown_quick()
    assert rt.state.session.status is SessionStatus.ENDED
