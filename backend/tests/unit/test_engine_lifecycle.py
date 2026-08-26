"""单元测试：辅导引擎生命周期（bg 任务持有 / recompute 串行 / bound 守卫）。

覆盖：_track 强引用持有、_recompute_lock 串行化、_bound 守卫阻断自延续。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.services.coaching.engine import CoachingEngine


def _engine(make_state):
    e = CoachingEngine(make_state(), lambda m: None)
    e._llm = AsyncMock()
    # Stage 4 pivot：production 经 chat_text 取原文 → JSON parse 在 engine 侧做。
    e._llm.chat_text = AsyncMock(return_value='{"items": []}')
    e._get_llm = lambda: e._llm  # _llm_with_timeout 经 _get_llm() 取 provider
    return e


async def test_recompute_serializes_under_lock(make_state):
    """两个并发 _recompute 必须串行：LLM 临界区不重叠。"""
    e = _engine(make_state)
    in_flight = 0
    max_overlap = 0

    async def slow(*a, **kw):  # engine 调 chat_text(s, u, json_mode=True)，**kw 兼容
        nonlocal in_flight, max_overlap
        in_flight += 1
        max_overlap = max(max_overlap, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return '{"items": []}'

    e._llm.chat_text = AsyncMock(side_effect=slow)
    await asyncio.gather(e._track(e._recompute()), e._track(e._recompute()))
    # 锁生效 → LLM 临界区不重叠（max_overlap==1）；移除锁则 ==2，断言失败
    assert max_overlap == 1


async def test_track_holds_strong_reference(make_state):
    e = _engine(make_state)
    e._llm.chat_text = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(0.05, result='{"items": []}'))
    _ = e._track(e._recompute())
    assert len(e._bg) >= 1
    await asyncio.sleep(0.2)
    assert len(e._bg) == 0  # 完成后自动移出


async def test_drain_bg_cancels_inflight(make_state):
    e = _engine(make_state)
    e._llm.chat_text = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(10, result='{"items": []}'))
    e._track(e._recompute())
    await asyncio.sleep(0.02)  # 让它进入 LLM 等待
    await e._drain_bg()
    assert len(e._bg) == 0
    assert e._sched_task is None


async def test_unbind_sets_bound_and_blocks_self_perpetuation(make_state):
    e = _engine(make_state)
    e._llm.chat_text = AsyncMock(side_effect=lambda *a: asyncio.sleep(0.01, result='{"items": []}'))
    e.on_unbind()
    assert e._bound is False
    await e._recompute()
    await asyncio.sleep(0.05)
    # unbind 后 finally 不重新武装调度任务
    assert e._sched_task is None or e._sched_task.done()


async def test_on_end_final_runs_after_inflight(make_state):
    """end 时若有在途 _recompute，final 排在其后跑（都落盘），结果新鲜。"""
    e = _engine(make_state)
    started = asyncio.Event()
    async def slow(*a, **kw):  # engine 调 chat_text(s, u, json_mode=True)，**kw 兼容
        started.set()
        await asyncio.sleep(0.05)
        return '{"items": [{"id": "pain", "text": "在途结果", "status": "todo"}]}'
    e._llm.chat_text = AsyncMock(side_effect=slow)
    e._track(e._recompute())  # 起一个在途
    await started.wait()
    await e.on_end()  # 应等在途完，再跑 final
    assert e._closed is True
    assert len(e._bg) == 0  # drain 过


async def test_on_end_best_effort_on_timeout(make_state):
    """final 超时 → 不卡死，best-effort 落盘。"""
    e = _engine(make_state)
    e._llm_timeout_s = 0.01
    async def hang(*a, **kw):  # engine 调 chat_text(s, u, json_mode=True)，**kw 兼容
        await asyncio.sleep(10)
    e._llm.chat_text = AsyncMock(side_effect=hang)
    await asyncio.wait_for(e.on_end(), timeout=5)
    assert e._closed is True
