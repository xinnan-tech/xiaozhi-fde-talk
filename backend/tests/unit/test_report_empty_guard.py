"""#166：空访谈（无任何可读段）拒出报告，路由与 generator 双层守卫。"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.reports import generator


@dataclass
class _FakeSeg:
    """最小 TranscriptSegment 替身——只 _seg_text / seg_id 被读。"""
    seg_id: str
    text: str
    corrected_text: str = ""


@dataclass
class _FakeSession:
    template_id: str = "t1"
    template_snapshot: dict | None = None
    base_info: dict = field(default_factory=dict)
    goal: str | None = None


@dataclass
class _FakeState:
    transcript: list = field(default_factory=list)
    session: _FakeSession = field(default_factory=lambda: _FakeSession())
    items: list = field(default_factory=list)


@pytest.mark.asyncio
async def test_get_or_generate_empty_transcript_short_circuits(monkeypatch):
    """空 transcript → 返 ("empty", "")，不调 LLM、不落库、不触发 on_ready。"""
    state = _FakeState(transcript=[])  # 空：核心触发条件

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=None),
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="LLM 居然被调到 = 测试失败")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    # resolve_template 必须**不能**被调到——空 transcript 短路在前面
    monkeypatch.setattr(generator, "resolve_template", MagicMock(
        side_effect=AssertionError("resolve_template 不该被空 transcript 调用"),
    ))

    on_ready_mock = AsyncMock()
    status, md = await generator.get_or_generate("s-empty", on_ready=on_ready_mock)

    # 关键断言：空 status + 空内容，LLM 与 DB 都没被碰
    assert status == "empty"
    assert md == ""
    llm.chat_text.assert_not_called()
    upsert_mock.assert_not_called()
    # "empty" 不广播（runtime 仅识别 ready/failed；HTTP 层 GET/POST 在此处翻 409）
    on_ready_mock.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_generate_segments_with_empty_text_short_circuits(monkeypatch):
    """段存在但每段 text/corrected_text 都为空（如 ASR 全失败）→ 同样短路。"""
    seg = _FakeSeg(seg_id="s1", text="", corrected_text="")
    state = _FakeState(transcript=[seg])

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=None),
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="LLM 居然被调到 = 测试失败")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "resolve_template", MagicMock(
        side_effect=AssertionError("resolve_template 不该被空内容段调用"),
    ))

    on_ready_mock = AsyncMock()
    status, md = await generator.get_or_generate("s-empty-segs", on_ready=on_ready_mock)

    assert status == "empty"
    assert md == ""
    llm.chat_text.assert_not_called()
    upsert_mock.assert_not_called()
    on_ready_mock.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_generate_non_empty_transcript_still_calls_llm(monkeypatch):
    """非空 transcript → 走正常路径：调 LLM、落库——守卫不误伤正常请求。"""
    seg = _FakeSeg(seg_id="s1", text="我们用了 PostgreSQL。")
    state = _FakeState(transcript=[seg])

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=None),  # 缓存未命中
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="## 报告\n正常内容")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "resolve_template", lambda _id, _snap: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s-ok")

    assert status == "ready"
    assert "报告" in md
    llm.chat_text.assert_awaited_once()
    upsert_mock.assert_awaited_once()


def test_route_status_gate_includes_only_terminal_states():
    """_REPORT_READY_STATUSES 必须只含 ended/extracting/done——把 created/in_progress 等挡在外面。"""
    from app.transport.http.routes.reports import _REPORT_READY_STATUSES
    from app.domain.session import SessionStatus

    expected = {SessionStatus.ENDED, SessionStatus.EXTRACTING, SessionStatus.DONE}
    assert _REPORT_READY_STATUSES == expected, (
        f"报告就绪闸门状态集合错：实际={_REPORT_READY_STATUSES} 期望={expected}"
    )

    # 反向断言：created/setting_up/in_progress/suspended 都被排除
    blocked = {SessionStatus.CREATED, SessionStatus.SETTING_UP,
               SessionStatus.IN_PROGRESS, SessionStatus.SUSPENDED}
    assert _REPORT_READY_STATUSES.isdisjoint(blocked), (
        f"早期状态被误放进就绪集合：{blocked & _REPORT_READY_STATUSES}"
    )
