"""报告 prompt 防编造（issue #45）回归。

两道防线：
1. `_REPORT_SYSTEM` 必须含「禁止编造」硬规则——禁止 LLM 在 transcript 外捏造
   名字 / 数字 / 比例 / 时长 / 合规名等具体信息，并把没讨论过的事项写兜底短语。
2. `_build_user` 必须把 state.items（id / text / status / covered_segments 派生
   自 corrected_segments.keys）注入 user prompt——给 LLM 一张「已覆盖 vs 未覆盖」
   的结构化地图，让 LLM 区分 done（有 seg 可引）vs todo/new（无 seg 不可引）。

两道防线都断言 prompt 形态本身——内容生成靠真 LLM，单测无意义。形态约束
是防止后续重构把这两条防线偷偷拿掉（generator-fakerec-test-pattern 风格）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

from app.domain.coaching import CoachingItem, ItemStatus
from app.domain.session import Session, SessionStatus, TranscriptSegment
from app.domain.session_state import SessionState
from app.services.reports import generator


# ────────────── 防编造硬规则（系统 prompt） ──────────────


def test_system_has_grounding_rule():
    """base 必须声明禁止编造——LLM 据此知道「没原文就写兜底短语」，不擅自填补。"""
    body = generator._REPORT_SYSTEM.lower()
    # 关键短语都得在：禁止 fabricate / 不准 invent / 不准 hallucinate
    assert "fabricat" in body or "hallucinat" in body, (
        f"base 未含禁止 fabricate/hallucinate 的硬规则：{body[:400]!r}"
    )
    assert "invent" in body, (
        f"base 未含禁止 invent 的硬规则：{body[:400]!r}"
    )


def test_system_enumerates_forbidden_specifics():
    """base 必须点名禁止的具体信息类别——只有「禁止编造」太抽象，LLM 还是会编。

    经验：name/number/date 三件套太低——LLM 会改去编 percentages / file path /
    duration / version string。规则须覆盖至少 4 类才算到位。
    """
    body = generator._REPORT_SYSTEM.lower()
    forbidden_kinds = ["name", "number", "date", "percentage", "duration", "file path"]
    present = [k for k in forbidden_kinds if k in body]
    assert len(present) >= 4, (
        f"base 未点名至少 4 类禁止编造的具体信息（实测：3 类 LLM 仍编 percentages），"
        f"实际出现 {present}：{body[:400]!r}"
    )


def test_system_treats_skipped_ignored_as_uncovered():
    """Grounding rule 必须把 skipped / ignored 当作未覆盖——否则 LLM 看到这两态会猜。

    实测看 qwen-plus 不严格区分 status 五态，但加这条 sentinel 防止后续模型/规则
    漂移时让 skipped 项"有 seg 可引"造成幻觉回归。
    """
    body = generator._REPORT_SYSTEM.lower()
    # grounding rule 段必须同时点 skipped 和 ignored
    assert "skipped" in body and "ignored" in body, (
        f"base 未点名 skipped/ignored 也按未覆盖处理——LLM 可能误读这两态：{body[:600]!r}"
    )


def test_system_mandates_fallback_when_no_transcript():
    """base 必须明示「短/空 transcript → 短诚实报告，不要用 plausible-but-fabricated 内容拉长」。"""
    body = generator._REPORT_SYSTEM.lower()
    # 关键概念同时出现：fallback 短语 + 「短」（短报告） + 「fabricated」
    assert "fallback" in body, f"base 未提 fallback 短语：{body[:400]!r}"
    assert "short" in body or "honest" in body, (
        f"base 未提「短/诚实」报告原则——LLM 会拉长编造：{body[:400]!r}"
    )


# ────────────── state.items 注入（用户 prompt） ──────────────


@dataclass
class _CapturedCall:
    system: str
    user: str


def _patch_for_capture(monkeypatch, state: SessionState, captured: list[_CapturedCall]):
    """让 generate_report 把调到的 (system, user) 抓出来。LLM 返回空串防 pivot 副作用。"""
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    template = MagicMock()
    template.report = MagicMock(doc="## 背景\n{{ 简单说说项目背景 }}")
    monkeypatch.setattr(generator, "get_template", lambda _id: template)

    async def _capture_chat(system, user):
        captured.append(_CapturedCall(system=system, user=user))
        return ""  # 空输出：sanitize_report_markdown 之后是空串，但 prompt 已抓到

    llm = MagicMock()
    llm.chat_text = _capture_chat
    monkeypatch.setattr(generator, "get_llm", lambda: llm)


def _make_session(template_id: str = "t1") -> Session:
    return Session(
        id="sess-1",
        template_id=template_id,
        status=SessionStatus.IN_PROGRESS,
        base_info={"project": "演示项目", "interviewee": "张三"},
        goal="了解需求",
    )


def _make_state(items: list[CoachingItem]) -> SessionState:
    return SessionState(
        session=_make_session(),
        items=items,
        transcript=[
            TranscriptSegment(seg_id="s1", text="我们项目用了 PostgreSQL。", final=True, start_ms=0),
            TranscriptSegment(seg_id="s2", text="并发大约 100 QPS。", final=True, start_ms=1000),
        ],
    )


async def test_user_prompt_includes_coverage_block_header(monkeypatch):
    """user prompt 必须含【辅导清单覆盖情况】标题块——LLM 据此读结构化覆盖地图。"""
    captured: list[_CapturedCall] = []
    state = _make_state([
        CoachingItem(id="c1", text="数据库选型", status=ItemStatus.DONE,
                     corrected_segments={"s1": "我们项目用了 PostgreSQL。"}),
    ])
    _patch_for_capture(monkeypatch, state, captured)

    await generator.generate_report(state, MagicMock(report=MagicMock(doc="")), "zh_cn")

    assert captured, "LLM 未被调用"
    user = captured[0].user
    assert "【辅导清单覆盖情况】" in user, (
        f"user prompt 缺辅导清单覆盖情况块：{user[:500]!r}"
    )


async def test_user_prompt_serializes_item_id_text_status(monkeypatch):
    """每条 item 的 id / text / status 都要进入 user prompt。"""
    captured: list[_CapturedCall] = []
    state = _make_state([
        CoachingItem(id="c1", text="数据库选型", status=ItemStatus.DONE,
                     corrected_segments={"s1": "用了 PostgreSQL。"}),
        CoachingItem(id="c2", text="合规要求", status=ItemStatus.TODO),
    ])
    _patch_for_capture(monkeypatch, state, captured)

    await generator.generate_report(state, MagicMock(report=MagicMock(doc="")), "zh_cn")

    user = captured[0].user
    assert "id=c1" in user, f"item c1 id 未出现在 user prompt：{user[:800]!r}"
    assert "数据库选型" in user, f"item c1 text 未出现在 user prompt：{user[:800]!r}"
    assert "status=done" in user, f"item c1 status 未出现在 user prompt：{user[:800]!r}"
    assert "id=c2" in user, f"item c2 id 未出现在 user prompt：{user[:800]!r}"
    assert "status=todo" in user, f"item c2 status 未出现在 user prompt：{user[:800]!r}"


async def test_user_prompt_serializes_covered_segments(monkeypatch):
    """done 项的 covered_segments 必须从 corrected_segments.keys() 派生后注入。"""
    captured: list[_CapturedCall] = []
    state = _make_state([
        CoachingItem(id="c1", text="数据库选型", status=ItemStatus.DONE,
                     corrected_segments={"s1": "用了 PostgreSQL。", "s2": "并发 100 QPS。"}),
    ])
    _patch_for_capture(monkeypatch, state, captured)

    await generator.generate_report(state, MagicMock(report=MagicMock(doc="")), "zh_cn")

    user = captured[0].user
    # 派生自 corrected_segments.keys() = {"s1","s2"}，逗号分隔
    assert "covered_segments=[s1,s2]" in user or "covered_segments=[s2,s1]" in user, (
        f"done 项 covered_segments 未派生并注入：{user[:800]!r}"
    )


async def test_user_prompt_marks_todo_items_with_dash(monkeypatch):
    """todo/new 项的 covered_segments 必须是 `-`（占位）——LLM 据此识别「无 seg 可引」。"""
    captured: list[_CapturedCall] = []
    state = _make_state([
        CoachingItem(id="c-todo", text="合规要求", status=ItemStatus.TODO),
        CoachingItem(id="c-new", text="备份策略", status=ItemStatus.NEW),
    ])
    _patch_for_capture(monkeypatch, state, captured)

    await generator.generate_report(state, MagicMock(report=MagicMock(doc="")), "zh_cn")

    user = captured[0].user
    # 两条 item 都应出现 covered_segments=[-]
    todo_line = next((ln for ln in user.splitlines() if "id=c-todo" in ln), None)
    new_line = next((ln for ln in user.splitlines() if "id=c-new" in ln), None)
    assert todo_line is not None and "covered_segments=[-]" in todo_line, (
        f"todo 项 covered_segments 未标 -：{todo_line!r}"
    )
    assert new_line is not None and "covered_segments=[-]" in new_line, (
        f"new 项 covered_segments 未标 -：{new_line!r}"
    )


async def test_user_prompt_handles_empty_items(monkeypatch):
    """state.items 为空时 user prompt 必须显式说明，不留 LLM 自由发挥的余地。"""
    captured: list[_CapturedCall] = []
    state = SessionState(
        session=_make_session(),
        items=[],
        transcript=[TranscriptSegment(seg_id="s1", text="短对话", final=True, start_ms=0)],
    )
    _patch_for_capture(monkeypatch, state, captured)

    await generator.generate_report(state, MagicMock(report=MagicMock(doc="")), "zh_cn")

    user = captured[0].user
    assert "【辅导清单覆盖情况】" in user
    assert "(no coaching items tracked)" in user, (
        f"空 items 时未显式说明——LLM 可能编造覆盖情况：{user[:500]!r}"
    )


async def test_system_does_not_have_empty_coverage_signal_leak():
    """system 可以指引 LLM 使用 coverage block（提到名词），但不该**塞**真实数据。

    区分：「告诉 LLM 你会拿到这块数据」vs「把这块数据的实例填进去」——后者
    会把 user 侧的注入冗余成 system 数据，跨 call 复用会错位。允许 system 含
    `covered_segments` 字样作为使用说明，但不允许出现 `id=` `status=` 真实行。
    """
    body = generator._REPORT_SYSTEM
    assert "covered_segments=" not in body, (
        "covered_segments= 不该出现在 system 里——那是 user 注入的实例化字段"
    )
    assert "id=c" not in body and "id=item" not in body, (
        f"system 不该有 item 实例行：{body[:600]!r}"
    )
