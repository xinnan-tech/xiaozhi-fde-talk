"""单元测试：辅导引擎 CoachingEngine（coaching/engine）。

不依赖外部服务（LLM 用 AsyncMock），验证首算 / _apply / 计时器 / 超时。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.domain.coaching import ItemStatus
from app.services.coaching.contract import validate_llm_output
from app.services.coaching.engine import CoachingEngine


async def test_engine_first_compute(make_state):
    state = make_state()
    calls = []

    async def send(msg):
        calls.append(msg)

    engine = CoachingEngine(state, send)
    await engine.first_compute()
    msg = calls[0]
    assert msg["phase"] == "final" and msg["version"] == 1 and len(msg["items"]) == 6
    assert [it["id"] for it in msg["items"]] == [
        "objective", "pain", "current_solution", "constraints", "decision", "success",
    ]


async def test_engine_apply_done_from_llm(make_state):
    engine = CoachingEngine(make_state(), lambda m: None)
    items = validate_llm_output([
        {"id": "objective", "text": "目标已明确", "status": "done", "covered_segments": ["s1"]},
        {"id": "pain", "text": "痛点", "status": "todo"},
    ])
    result = engine._apply(items)
    assert result[0].id == "objective" and result[0].status == ItemStatus.DONE and result[0].priority == 1


async def test_engine_apply_null_id_backend_alloc(make_state):
    engine = CoachingEngine(make_state(), lambda m: None)
    result = engine._apply(validate_llm_output([{"id": None, "text": "新发现的问题", "status": "new"}]))
    assert len(result) == 1 and result[0].id.startswith("n")


async def test_engine_apply_skipped_overrides(make_state):
    state = make_state()
    state.skipped_ids.add("pain")
    engine = CoachingEngine(state, lambda m: None)
    result = engine._apply(validate_llm_output([{"id": "pain", "text": "痛点", "status": "todo"}]))
    assert result[0].status == ItemStatus.SKIPPED


async def test_engine_apply_ignored_overrides(make_state):
    state = make_state()
    state.ignored_ids.add("pain")
    engine = CoachingEngine(state, lambda m: None)
    result = engine._apply(validate_llm_output([{"id": "pain", "text": "痛点", "status": "done"}]))
    assert result[0].status == ItemStatus.IGNORED


async def test_engine_apply_preserves_ignored_when_llm_drops(make_state):
    """LLM 因对话已覆盖把已忽略项标 done 整条丢出 result：补回快照保留 IGNORED。"""
    state = make_state()
    # state 已有 objective 项（用户已 ignore）
    state.items = [
        type(state.items[0])(id="objective", text="目标是什么", status=ItemStatus.TODO, reason="", priority=1, desc=""),
    ]
    state.ignored_ids.add("objective")
    engine = CoachingEngine(state, lambda m: None)
    # LLM 输出不含 objective（认为已覆盖）
    result = engine._apply(validate_llm_output([{"id": "pain", "text": "痛点", "status": "todo"}]))
    by_id = {it.id: it for it in result}
    assert "objective" in by_id, "用户忽略的项被 LLM 丢弃后必须补回"
    assert by_id["objective"].status == ItemStatus.IGNORED
    assert by_id["objective"].text == "目标是什么"


async def test_engine_apply_preserves_skipped_when_llm_drops(make_state):
    """LLM 丢被跳过的项：补回并保留 SKIPPED。"""
    state = make_state()
    state.items = [
        type(state.items[0])(id="constraints", text="约束", status=ItemStatus.TODO, reason="", priority=4, desc=""),
    ]
    state.skipped_ids.add("constraints")
    engine = CoachingEngine(state, lambda m: None)
    result = engine._apply(validate_llm_output([{"id": "pain", "text": "痛点", "status": "todo"}]))
    by_id = {it.id: it for it in result}
    assert by_id["constraints"].status == ItemStatus.SKIPPED


async def test_engine_apply_dedupe(make_state):
    engine = CoachingEngine(make_state(), lambda m: None)
    result = engine._apply(validate_llm_output([
        {"id": "pain", "text": "first", "status": "todo"},
        {"id": "pain", "text": "second", "status": "done"},
    ]))
    assert len(result) == 1 and result[0].text == "first"


async def test_engine_apply_coverage_index(make_state):
    state = make_state()
    engine = CoachingEngine(state, lambda m: None)
    engine._apply(validate_llm_output([
        {"id": "objective", "text": "目标", "status": "done", "covered_segments": ["s1", "s3"]},
    ]))
    assert state.coverage["objective"] == ["s1", "s3"]


async def test_engine_on_end_marks_closed(make_state):
    engine = CoachingEngine(make_state(), lambda m: None)
    await engine.first_compute()
    engine._in_progress = True
    await engine.on_end()
    assert engine._closed is True


async def test_engine_recompute_requires_llm(make_state):
    """_llm 未初始化 → _recompute fail-fast，不静默清空。"""
    engine = CoachingEngine(make_state(), lambda m: None)
    assert engine._llm is None
    import pytest
    with pytest.raises(RuntimeError):
        await engine._recompute()


async def test_engine_llm_timeout(make_state):
    """chat_text 调 chat_text(..., json_mode=True) + wait_for 超时 → TimeoutError 透传。"""
    engine = CoachingEngine(make_state(), lambda m: None)
    engine._llm = AsyncMock()
    engine._llm.chat_text = AsyncMock(return_value='{"items": []}')
    engine._get_llm = lambda: engine._llm

    async def raise_timeout(_future, *, timeout=None):  # pylint: disable=unused-argument
        raise asyncio.TimeoutError

    with patch("asyncio.wait_for", side_effect=raise_timeout):
        try:
            await engine._llm_pivot_then_parse_json("sys", lambda _l: "sys", "user", "en")
            assert False, "should raise TimeoutError"
        except asyncio.TimeoutError:
            pass


async def test_engine_llm_success(make_state):
    """chat_text 返回 JSON 字符串 → _llm_pivot_then_parse_json 解析为 dict。"""
    engine = CoachingEngine(make_state(), lambda m: None)
    engine._llm = AsyncMock()
    engine._llm.chat_text = AsyncMock(return_value='{"items": []}')
    engine._get_llm = lambda: engine._llm
    parsed = await engine._llm_pivot_then_parse_json(
        "sys", lambda _l: "sys", "user", "en",
    )
    assert parsed == {"items": []}
