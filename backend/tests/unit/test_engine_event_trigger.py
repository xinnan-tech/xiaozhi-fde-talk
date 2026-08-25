"""单元测试：教练引擎事件驱动触发（停顿防抖 / 段数阈值 / 限频 / 生命周期守卫）。

时间参数全部取毫秒级真实值（0.01~0.05s），不 mock 时钟。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.services.coaching.engine import CoachingEngine


def _engine(make_state, **overrides):
    e = CoachingEngine(make_state(), lambda m: None)
    # 标记首评已生成 → first_compute 不再后台补跑 first_generate，本测试只关心
    # 防抖/段数阈值/限频这些事件触发路径，first_generate 单独有其它测试覆盖。
    e.state.session.first_batch_generated = True
    e._llm = AsyncMock()
    # engine 走 chat_text(..., json_mode=True)，再由 _extract_json_dict 从 raw text
    # 抽 {...} 块解析（替代旧的 chat_json 返回 dict 直传）。
    # 中文项让 pivot 看到 CJK 脚本 → 不触发 fallback 重试，测试只关心事件触发计数。
    e._llm.chat_text = AsyncMock(return_value='{"items": [{"text": "测试项"}]}')
    e._get_llm = lambda: e._llm
    # 单测不应真落库（test-session-1 行可能 stale；schema 演进后会因 NOT NULL 撞墙）。
    e._persist = AsyncMock()
    e._pause_s = overrides.get("pause_s", 0.02)
    e._max_pending_segments = overrides.get("max_pending", 8)
    e._min_interval_s = overrides.get("min_interval", 0.0)
    return e


def _add_seg(state, n=1):
    from app.domain.session import TranscriptSegment
    for i in range(n):
        state.transcript.append(TranscriptSegment(
            seg_id=state.next_seg_id(), start_ms=0, speaker="unknown",
            text=f"第{i}句", final=True))


async def test_pause_debounce_fires_recompute(make_state):
    e = _engine(make_state)
    await e.first_compute()
    _add_seg(e.state)
    e.on_utterance()
    await asyncio.sleep(0.1)  # 防抖 0.02s 到期 + LLM mock 立即返回
    assert e._llm.chat_text.await_count >= 1
    await e._drain_bg()


async def test_debounce_rearmed_by_new_utterance(make_state):
    """防抖期内新句到达 → 计时重置，不提前触发。"""
    e = _engine(make_state, pause_s=0.1)
    await e.first_compute()
    _add_seg(e.state)
    e.on_utterance()
    await asyncio.sleep(0.05)
    e.on_utterance()  # 重臂：从现在起再等 0.1s
    await asyncio.sleep(0.06)
    assert e._llm.chat_text.await_count == 0  # 未到期
    await asyncio.sleep(0.1)
    assert e._llm.chat_text.await_count == 1
    await e._drain_bg()


async def test_no_fire_when_window_empty(make_state):
    """无新段（游标已消费）→ 防抖到期不调 LLM。"""
    e = _engine(make_state)
    e.state.session.first_batch_generated = True  # 首评已生成，排除后台补跑对计数的干扰
    await e.first_compute()
    e._arm(e._pause_s, "测试")
    await asyncio.sleep(0.1)
    assert e._llm.chat_text.await_count == 0


async def test_segment_threshold_fires_without_pause(make_state):
    """攒够 max_pending_segments 条 → 不等防抖立即触发。"""
    e = _engine(make_state, pause_s=10.0, max_pending=3)
    await e.first_compute()
    _add_seg(e.state, 3)
    for _ in range(3):
        e.on_utterance()
    await asyncio.sleep(0.1)
    assert e._llm.chat_text.await_count == 1
    await e._drain_bg()


async def test_min_interval_defers_but_not_drops(make_state):
    """距上次重算不足 min_interval → 推迟触发，窗口不丢。"""
    e = _engine(make_state, pause_s=0.01, min_interval=0.15)
    await e.first_compute()
    import time
    e._last_ts = time.time()  # 模拟 0.15s 内刚重算过
    _add_seg(e.state)
    e.on_utterance()
    await asyncio.sleep(0.05)
    assert e._llm.chat_text.await_count == 0   # 被限频推迟
    await asyncio.sleep(0.2)
    assert e._llm.chat_text.await_count == 1   # 满间隔后照常触发
    await e._drain_bg()


async def test_no_second_call_while_in_progress(make_state):
    """LLM 在途时触发到达 → 不并发第二个调用；完成后窗口增长则续算。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def hang(*a, **kw):  # engine 调 chat_text(s, u, json_mode=True)，**kw 兼容
        started.set()
        await release.wait()
        # 中文项让 pivot 看到 CJK 脚本 → 不触发 fallback 重试，await_count 保持 1
        return '{"items": [{"text": "测试项"}]}'

    e = _engine(make_state, pause_s=0.01)
    e._llm.chat_text = AsyncMock(side_effect=hang)
    await e.first_compute()
    _add_seg(e.state)
    e.on_utterance()
    await started.wait()
    _add_seg(e.state, 2)      # 在途期间又来新段
    e.on_utterance()
    await asyncio.sleep(0.05)
    assert e._llm.chat_text.await_count == 1  # 无第二个并发调用
    release.set()
    await asyncio.sleep(0.05)
    # 失败/续算路径：hang 正常返回 → 游标推进 → 不再有第二次
    assert e._llm.chat_text.await_count == 1
    await e._drain_bg()


async def test_listen_pause_blocks_fire(make_state):
    e = _engine(make_state, pause_s=0.01)
    await e.first_compute()
    _add_seg(e.state)
    e.on_utterance()
    e.on_listen_pause()
    await asyncio.sleep(0.1)
    assert e._llm.chat_text.await_count == 0
    assert e._sched_task is None or e._sched_task.done()


async def test_on_end_cancels_scheduler(make_state):
    e = _engine(make_state, pause_s=0.01)
    await e.first_compute()
    _add_seg(e.state)
    e.on_utterance()
    await e.on_end()
    assert e._closed is True
    assert e._sched_task is None


async def test_failure_resends_old_items_then_retries(make_state):
    """首次重算 LLM 失败 → 旧清单以 final 重推保留；满 min_interval 后续算成功。"""
    from app.adapters.llm.base import LLMError

    sent: list[dict] = []

    async def send(m: dict) -> None:
        sent.append(m)

    e = CoachingEngine(make_state(), send)
    e._llm = AsyncMock()
    e._llm.chat_text = AsyncMock(side_effect=[LLMError("boom"), '{"items": [{"text": "测试项"}]}'])  # 中文防 pivot 重试
    e._get_llm = lambda: e._llm
    e._persist = AsyncMock()  # 同上，避免落库
    e._pause_s = 0.01
    e._min_interval_s = 0.1
    await e.first_compute()
    old_items = [it.model_dump(mode="json") for it in e.state.items]
    _add_seg(e.state)
    e.on_utterance()
    await asyncio.sleep(0.05)
    finals = [m for m in sent if m["type"] == "coaching.update" and m["phase"] == "final"]
    assert e._llm.chat_text.await_count == 1          # 第一次调用失败
    assert len(finals) == 2                           # 首算 + 失败后的旧清单重推
    assert finals[1]["items"] == old_items            # 失败 → 推回上一份清单
    await asyncio.sleep(0.2)
    assert e._llm.chat_text.await_count == 2          # 续算成功，恰好两次
    assert e._transcript_len_at_last == len(e.state.transcript)  # 游标推进 → 无第三次
    await e._drain_bg()


async def test_on_listen_stopped_empty_window_no_call(make_state):
    """listen 停止时窗口为空（游标已消费）→ 不触发重算。"""
    e = _engine(make_state)
    e.state.session.first_batch_generated = True  # 首评已生成，排除后台补跑对计数的干扰
    await e.first_compute()
    e.on_listen_stopped()
    await asyncio.sleep(0.05)
    assert e._llm.chat_text.await_count == 0


async def test_on_listen_stopped_skips_while_in_progress(make_state):
    """listen 停止时已有在途重算 → 跳过，窗口留给后续事件消费。"""
    e = _engine(make_state)
    await e.first_compute()
    _add_seg(e.state)
    e._in_progress = True
    e.on_listen_stopped()
    await asyncio.sleep(0.05)
    assert e._llm.chat_text.await_count == 0
    e._in_progress = False
