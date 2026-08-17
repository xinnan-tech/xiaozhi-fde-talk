from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.services.sessions.runtime import SessionRuntime


async def test_many_segments_one_debounced_save(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    calls = []

    async def save(*, fields=None):
        calls.append(len(rt.state.transcript))

    rt._save_state = save
    rt._flush_interval_s = 0.05
    rt._flush_dirty_segments = 3
    for i in range(10):
        await rt._on_utterance(f"段{i}", True, 16000 * i)
    # 去抖/阈值触发在窗口内最多落盘一次
    await asyncio.sleep(0.01)
    assert len(calls) <= 1


async def test_unbind_flushes_pending(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved = []

    async def save(*, fields=None):
        saved.append(True)

    rt._save_state = save
    await rt._on_utterance("待落盘", True, 0)
    saved.clear()
    rt.engine.on_unbind = lambda: None
    await rt.unbind()
    assert saved == [True]


async def test_force_flush_saves_even_when_no_dirty_segments(make_state):
    """生命周期 flush 即使无脏转写也落盘——保留 consumed_seq 等非转写状态。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved = []

    async def save(*, fields=None):
        saved.append(True)

    rt._save_state = save
    await rt._force_flush()
    assert saved == [True]


async def test_threshold_triggers_immediate_flush(make_state):
    """脏段达阈值立即落盘，不等去抖窗口。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    calls = []

    async def save(*, fields=None):
        calls.append(len(rt.state.transcript))

    rt._save_state = save
    rt._flush_interval_s = 10.0  # 长窗口，确保只有阈值触发
    rt._flush_dirty_segments = 3
    for i in range(3):
        await rt._on_utterance(f"段{i}", True, 16000 * i)
    await asyncio.sleep(0.05)
    assert len(calls) == 1
    assert calls[0] == 3


async def test_recompute_and_utterance_serialize(make_state):
    """并发：一段转写 + 一次重算，持久化经 _utterance_lock 串行，无交错写崩溃。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._flush_interval_s = 10.0  # 抑制 lingering 去抖任务
    rt.engine._llm = AsyncMock()
    rt.engine._llm.chat_json = AsyncMock(return_value={"items": []})
    rt.engine._get_llm = lambda: rt.engine._llm
    log = []

    async def spy_save():
        async with rt._utterance_lock:
            log.append(("save", len(rt.state.transcript)))

    rt.engine._persist = spy_save
    await asyncio.gather(
        rt._on_utterance("x", True, 0),
        rt.engine._recompute(),
    )
    # 无交错写崩溃 + 状态一致
    assert len(rt.state.transcript) == 1
    # 重算落盘经 _persist 钩子：spy 恰好被调用一次
    assert len(log) == 1


async def test_persist_for_recompute_holds_utterance_lock(make_state):
    """_persist_for_recompute 在持 _utterance_lock 期间落盘——与 _on_utterance 建段串行。"""
    rt = SessionRuntime(make_state())
    held = {}
    rt._send_fn = AsyncMock()

    async def spy_save(*, fields=None):
        held["locked"] = rt._utterance_lock.locked()

    rt._save_state = spy_save
    await rt._persist_for_recompute()
    assert held["locked"] is True


async def test_listen_start_resets_asr_dead(make_state, monkeypatch):
    """listen:start 建新 provider 后清除 _asr_dead——单次 ASR 抖动不永久哑掉音频。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._asr_dead = True
    rt.pipeline.listen_start = AsyncMock()
    rt.engine.on_listen_resume = lambda: None
    import app.services.sessions.runtime as _rt
    monkeypatch.setattr(_rt, "_touch", lambda sid: None)
    await rt.listen_start()
    assert rt._asr_dead is False
