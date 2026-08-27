"""· WS 出站发送加锁：_raw_send 串行化并发调用（H4）。

runtime 侧 _raw_send 与 ASR 收包、coaching 推送并发发送会在 safe_send 的
await 点交错，破坏帧边界。_raw_send 持有与 ASR 客户端对称的 _send_lock。
"""
from __future__ import annotations

import asyncio

import pytest

from app.domain.session import Session, SessionStatus
from app.services.sessions.runtime import SessionRuntime
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


def _make_runtime() -> SessionRuntime:
    tpl = get_template("pm-research")
    session = Session(
        id="s1",
        template_id="pm-research",
        status=SessionStatus.IN_PROGRESS,
    )
    return SessionRuntime(state=SessionState.initial(session, tpl))


@pytest.mark.asyncio
async def test_raw_send_serializes_concurrent_calls():
    """两个并发 _raw_send 必须串行执行（验证 _send_lock）。"""
    runtime = _make_runtime()

    call_order: list[str] = []

    async def slow_send(msg: dict) -> None:
        if len(call_order) == 0:
            call_order.append("first_start")
            await asyncio.sleep(0.05)
            call_order.append("first_end")
        else:
            call_order.append("second_start")
            await asyncio.sleep(0.01)
            call_order.append("second_end")

    runtime._send_fn = slow_send

    t1 = asyncio.create_task(runtime._raw_send({"type": "a"}))
    t2 = asyncio.create_task(runtime._raw_send({"type": "b"}))
    await asyncio.gather(t1, t2)

    # 无锁：first_end 会落在 second_start 之后（交错）；有锁：严格串行
    idx_first_end = call_order.index("first_end")
    idx_second_start = call_order.index("second_start")
    assert idx_first_end < idx_second_start, f"_send 未串行化：{call_order}"
    assert call_order == ["first_start", "first_end", "second_start", "second_end"], (
        f"顺序错乱：{call_order}"
    )


@pytest.mark.asyncio
async def test_raw_send_returns_silently_when_no_send_fn():
    """_send_fn 为 None（reconnect 窗口期）静默返回，不抛。"""
    runtime = _make_runtime()
    runtime._send_fn = None
    await runtime._raw_send({"type": "x"})  # 不应抛
