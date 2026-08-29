"""LLM 纠错写回：done 项携带 corrected_segments → transcript.corrected_text。"""
from __future__ import annotations

from app.domain.coaching import CoachingItem, ItemStatus, LLMItem
from app.domain.session import TranscriptSegment


def test_llm_item_has_corrected_segments_field():
    it = LLMItem(id="q1", text="x", status=ItemStatus.DONE, corrected_segments={"s3": "纠正后"})
    assert it.corrected_segments == {"s3": "纠正后"}


def test_coaching_item_has_corrected_segments_field():
    it = CoachingItem(id="q1", text="x", status=ItemStatus.DONE, corrected_segments={"s3": "纠正后"})
    assert it.corrected_segments == {"s3": "纠正后"}


def test_transcript_segment_has_corrected_text_field():
    seg = TranscriptSegment(seg_id="s3", start_ms=0, end_ms=1000, speaker="I", text="错字原", corrected_text="错字纠正")
    assert seg.corrected_text == "错字纠正"
    # 默认空串，旧数据兼容
    seg2 = TranscriptSegment(seg_id="s4", start_ms=0, end_ms=1000, speaker="I", text="x")
    assert seg2.corrected_text == ""


def test_coaching_engine_apply_writes_corrections_to_transcript():
    """engine._apply：把 done 携带的 corrected_segments 写到对应 transcript 段。"""
    from app.services.coaching.engine import CoachingEngine
    from app.services.sessions.state import SessionState
    from app.domain.template import CoachingBlock, Template
    from app.domain.session import Session

    # 构造最小 SessionState + Template
    seg = TranscriptSegment(seg_id="s3", start_ms=0, end_ms=1000, speaker="I", text="原文")
    tpl = Template(id="t1", version="1", name="t", icon_alt="", coaching=CoachingBlock(playbook="", must_ask=[]))
    # 模板经 template_snapshot 注入：CoachingEngine.__init__ 里 resolve_template
    # 返 None 会抛 RuntimeError，而 "t1" 不在 loader 缓存里。
    sess = Session(id="sid", template_id="t1", template_version="1", user_id="u",
                   status="in_progress", base_info={}, goal="",
                   created_at=None, started_at=None, ended_at=None,
                   template_snapshot=tpl.model_dump(mode="json"))
    state = SessionState(session=sess, items=[], transcript=[seg])

    async def fake_send(_):
        pass

    eng = CoachingEngine(state, fake_send)

    llm_items = [
        LLMItem(
            id="q1", text="预算？", status=ItemStatus.DONE,
            reason="1万元/年", covered_segments=["s3"],
            corrected_segments={"s3": "原文纠正"},
        ),
    ]
    # 不调用 LLM：直接走 _apply
    out = eng._apply(llm_items)
    assert out[0].corrected_segments == {"s3": "原文纠正"}
    assert seg.corrected_text == "原文纠正"


def test_contract_parses_corrected_segments_only_on_done():
    from app.services.coaching.contract import validate_llm_item

    done = validate_llm_item({
        "id": "q1", "text": "预算？", "status": "done",
        "reason": "1万元", "covered_segments": ["s3"],
        "corrected_segments": {"s3": "纠正后"},
    })
    assert done.corrected_segments == {"s3": "纠正后"}

    # 非 done 一律清空
    todo = validate_llm_item({
        "id": "q2", "text": "目标？", "status": "todo",
        "corrected_segments": {"s3": "x"},  # 即便 LLM 写错给了
    })
    assert todo.corrected_segments == {}

    # 非 dict / 非 str 一律丢
    bad = validate_llm_item({
        "id": "q3", "text": "x", "status": "done",
        "corrected_segments": {"s3": 123, 4: "ok", "good": "ok"},
    })
    assert bad.corrected_segments == {"good": "ok"}


def test_build_user_uses_corrected_text():
    from app.services.coaching.prompt import build_user
    from app.services.sessions.state import SessionState
    from app.domain.template import CoachingBlock, Template
    from app.domain.session import Session

    sess = Session(id="sid", template_id="t1", template_version="1", user_id="u",
                   status="in_progress", base_info={}, goal="", created_at=None,
                   started_at=None, ended_at=None)
    state = SessionState(
        session=sess,
        items=[],
        transcript=[
            TranscriptSegment(seg_id="s3", start_ms=0, end_ms=1000,
                              speaker="I", text="原文错字", corrected_text="原文纠正"),
        ],
    )
    out = build_user(state)
    assert "[s3] 原文纠正" in out
    assert "原文错字" not in out