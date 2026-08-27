"""seg_id 独立计数器，与 transcript 长度解耦。

当前 next_seg_id() = f"s{len(transcript)+1}"：seg_id 完全由 transcript 长度推导。
一旦 transcript 被截断（P2-8b 软上限 pop 最早段），len 下降 → seg_id 回退 →
与已分配 id 冲突；coaching 的 coverage / covered_segments 索引随即错乱。
更隐蔽的是：截断后落盘 → 重载，重载对象的 len 已变小，新分配的 seg_id 直接撞上
仍存于 transcript 中的旧 id。

修复：独立自增计数器，且 __post_init__ 按 transcript 中已有的最大 seg 号对齐，
保证重载也不回退。
"""
from __future__ import annotations

from app.domain.session import TranscriptSegment
from app.services.sessions.state import SessionState


def test_seg_id_independent_of_transcript_length(make_state, make_seg):
    state = make_state()
    state.transcript = []

    first = state.next_seg_id()
    state.transcript.append(make_seg(first, "t1"))
    second = state.next_seg_id()
    state.transcript.append(make_seg(second, "t2"))

    # 模拟 P2-8b 软上限截断最早段
    state.transcript.pop(0)
    third = state.next_seg_id()

    # 当前 buggy：len 回到 1 → "s2" → 与 second 冲突
    assert third == "s3", f"截断后 seg_id 回退/冲突：got {third}"
    assert {first, second, third} == {"s1", "s2", "s3"}


def test_seg_id_survives_truncated_reconstruction(make_state, make_seg):
    """截断后落盘 → 重载：新 seg_id 不得撞上仍存于 transcript 的旧 id。"""
    state = make_state()
    state.transcript = []
    for _ in range(3):
        sid = state.next_seg_id()
        state.transcript.append(make_seg(sid, "t"))

    # 模拟软上限截断最早段，仅保留后两段（s2, s3）
    truncated = state.transcript[1:]

    # 模拟 _record_to_state 重载路径
    dumped = [seg.model_dump(mode="json") for seg in truncated]
    reloaded = SessionState(
        session=state.session,
        items=state.items,
        skipped_ids=state.skipped_ids,
        ignored_ids=state.ignored_ids,
        coverage=state.coverage,
        transcript=[TranscriptSegment(**d) for d in dumped],
    )
    nxt = reloaded.next_seg_id()

    # 当前 buggy：重载后 len=2 → "s3" → 撞上仍存在的 s3
    assert nxt == "s4", f"重载后 seg_id 未对齐已有 transcript：got {nxt}"
    existing = {seg.seg_id for seg in reloaded.transcript}
    assert nxt not in existing, "新 seg_id 与重载的旧 id 冲突"


def test_seg_id_monotonic_without_append(make_state):
    """连续分配不应依赖调用方在两次之间 append。"""
    state = make_state()
    state.transcript = []
    assert state.next_seg_id() == "s1"
    assert state.next_seg_id() == "s2"
    assert state.next_seg_id() == "s3"
