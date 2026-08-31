"""#166：空访谈 GET /report / POST /export 不再调 LLM、不再落库假报告。

两层防御：
1. 路由层 `get_interview_report` / `export_interview_report`：访谈 status 必须在
   {ended, extracting, done} 之一；早期状态（created/setting_up/in_progress/suspended）
   一律 409 HTTP_REPORT_NOT_READY，**绝不进入 generator**。
2. generator 层 `get_or_generate`：拿到 state 后再做一道 transcript 空检测——空就
   返 ("empty", "") + 跳过 DB upsert + 跳过 LLM。即便调用方绕过路由（e2e / 后台
   异步任务）直接调 generator 也守得住，避免 680 字虚构报告落库（#166 证据）。

测试只断 generator 的 internal 契约：路由层 409 是同步前置短路，不在单测范围里复刻
（FastAPI 路由级 happy path 已被现有 test_extract_endpoint_i18n.py 等覆盖，状态
闸门仅是在 route 层加一个 `if` 分支，没必要拉整套 TestClient 起来）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.reports import generator


# ────────────── generator：空 transcript 短路 ──────────────


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
    """空 transcript → 返 ("empty", "")，**不**调 LLM、**不**落库、**不**推 on_ready 误为 ready。"""
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
    # on_ready 必须被回调（status="empty"），但不能是 "ready"
    on_ready_mock.assert_awaited_once_with("empty")


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


# ────────────── 路由层：状态闸门（白盒——直接读路由函数体） ──────────────


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
