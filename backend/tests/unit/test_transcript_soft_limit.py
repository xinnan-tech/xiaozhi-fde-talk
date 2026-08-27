"""transcript 软上限：超过上限截断最早段，控内存。

长会话 transcript 无界增长，状态对象 + 每次落盘全列重序列化（P2-8c 前）开销随段数
线性放大。加软上限，超限 pop 最早段，保留最近 N 段。seg_id 由独立计数器分配
（P2-8a），截断不影响后续 seg_id 递增。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from app.core.policies import SessionPolicy
from app.services.sessions.runtime import SessionRuntime


async def test_overflow_truncates_oldest(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt.policy = SessionPolicy(transcript_soft_limit=3)
    rt._flush_dirty_segments = 999  # 避免循环中触发落盘

    for i in range(5):
        await rt._on_utterance(f"text {i}", is_final=True, start_sample=0)

    assert len(rt.state.transcript) == 3
    assert rt.state.transcript[0].text == "text 2"  # 最早 text0/text1 被截
    assert rt.state.transcript[-1].text == "text 4"


async def test_under_limit_keeps_all(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt.policy = SessionPolicy(transcript_soft_limit=10)
    rt._flush_dirty_segments = 999

    for i in range(3):
        await rt._on_utterance(f"text {i}", is_final=True, start_sample=0)

    assert len(rt.state.transcript) == 3


async def test_seg_id_keeps_increasing_after_truncation(make_state):
    """截断最早段后，新 seg_id 仍递增（依赖 P2-8a 独立计数器）。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt.policy = SessionPolicy(transcript_soft_limit=2)
    rt._flush_dirty_segments = 999

    for i in range(4):
        await rt._on_utterance(f"text {i}", is_final=True, start_sample=0)

    seg_ids = [s.seg_id for s in rt.state.transcript]
    assert seg_ids == ["s3", "s4"], f"截断后 seg_id 应继续递增，got {seg_ids}"
