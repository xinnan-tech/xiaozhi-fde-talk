"""报告骨架占位符：{{session.X}} 预填 + {{skill: ...}} 解析容错。

回归：
1. {{session.X}} 由后端从 state 预填，避免 transcript 里没 start_time/end_time 时
   LLM 原样留着（用户报告里的实际 bug）。
2. {{skill: ...}} 解析容错：LLM 给出的长中文描述（含 + / ；/ 空格）也能被识别。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.reports.generator import _prefill_session_placeholders
from app.services.reports.skill_renderer import _find_markers


@dataclass
class _FakeSession:
    base_info: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class _FakeState:
    session: _FakeSession = field(default_factory=_FakeSession)


# --- Bug 1: {{session.X}} 预填 ---

def test_prefill_session_basic():
    state = _FakeState(
        session=_FakeSession(
            base_info={"project": "彭经理项目", "interviewee": "彭经理"},
        )
    )
    doc = "# {{session.project}} 需求调研\n> 受访者：{{session.interviewee}}"
    out = _prefill_session_placeholders(doc, state)
    assert "{{session" not in out
    assert "彭经理项目" in out
    assert "彭经理" in out


def test_prefill_session_time_prefers_started_at():
    """实际 started_at 存在时，报告时间不应使用创建时填写的计划时间。"""
    state = _FakeState(
        session=_FakeSession(
            base_info={"project": "X", "start_time": "计划时间"},
            started_at=datetime(2026, 8, 11, 14, 30, tzinfo=timezone.utc),
        )
    )
    doc = "开始：{{session.start_time}}"
    out = _prefill_session_placeholders(doc, state)
    assert "计划时间" not in out
    expected = datetime(2026, 8, 11, 14, 30, tzinfo=timezone.utc).astimezone()
    assert expected.strftime("%Y-%m-%d %H:%M:%S") in out


def test_prefill_session_time_falls_back_to_base_info_before_start():
    """访谈尚未实际开始时，报告时间暂时使用计划时间。"""
    state = _FakeState(
        session=_FakeSession(
            base_info={"start_time": "手动填的时间"},
        )
    )
    doc = "开始：{{session.start_time}}"
    out = _prefill_session_placeholders(doc, state)
    assert "手动填的时间" in out
    assert "2026-08-11" not in out


def test_prefill_session_unknown_field_empties():
    """未知字段保留为空串而不是字面量（避免再次出现 `{{session.X}}` 残留）。"""
    state = _FakeState()
    doc = "X：{{session.nothing}}"
    out = _prefill_session_placeholders(doc, state)
    assert out == "X："


def test_prefill_session_keeps_chinese_placeholders():
    """`{{ 中文提示 }}`（LLM 填的）不被预填逻辑误伤。"""
    state = _FakeState(session=_FakeSession(base_info={"project": "X"}))
    doc = "{{ 项目背景 }}\n{{session.project}}"
    out = _prefill_session_placeholders(doc, state)
    assert out == "{{ 项目背景 }}\nX"


def test_prefill_session_single_curly_form():
    """回归 issue #122：单花括号 `{session.X}` 也走预填。

    qwen-plus 偶尔会把 `{{session.start_time}}` 吞掉一个 `{`，所以 L1 预填必
    须同时识别两种形态，避免 LLM 之后看到的是空字段再瞎填。
    """
    state = _FakeState(
        session=_FakeSession(base_info={"interviewee": "张三"}),
    )
    doc = "> 受访者：{session.interviewee}　开始：{session.start}　结束：{session.end}"
    out = _prefill_session_placeholders(doc, state)
    assert "{session" not in out
    assert "张三" in out
    # start/end 没有值 → 留空，不应回显字面量
    assert "开始：　结束：" in out


# --- Bug 2: {{skill: ...}} 容错解析 ---

def test_skill_no_inputs_simple():
    """标准无 inputs 形式。"""
    md = "before {{skill: echo}} after"
    markers = _find_markers(md)
    assert markers == [(7, 22, "echo", None)]


def test_skill_with_inputs():
    md = '{{skill: echo, inputs: {"x": 1}}}'
    markers = _find_markers(md)
    assert len(markers) == 1
    s, e, sid, raw = markers[0]
    assert sid == "echo"
    assert raw == '{"x": 1}'


def test_skill_chinese_long_description():
    """用户实测：LLM 输出含中文标点（+，；等）的 skill 描述。"""
    md = "{{skill: 优先支持iPad端离线转写+实时摘要生成；其次实现基于访谈目标的动态问题推荐引擎；第三步打通腾讯会议API实现远程场景自动接入}}"
    markers = _find_markers(md)
    assert len(markers) == 1
    s, e, sid, raw = markers[0]
    assert raw is None  # 没 inputs
    # 整段中文描述被吃下作 skill_id
    assert sid == "优先支持iPad端离线转写+实时摘要生成；其次实现基于访谈目标的动态问题推荐引擎；第三步打通腾讯会议API实现远程场景自动接入"
    # marker 整段被识别，可以替换
    assert md[s:e] == md[md.find("{{skill:"):md.find("}}") + 2]


def test_skill_mixed_in_text():
    md = "前文 {{skill: a}} 中间 {{skill: b, inputs: {\"k\":\"v\"}}} 末尾"
    markers = _find_markers(md)
    assert len(markers) == 2
    assert markers[0][2:] == ("a", None)
    assert markers[1][2:] == ("b", '{"k":"v"}')


def test_skill_no_close_skipped():
    """无 `}}` 闭合 → 跳过（不抛错，不死循环）。"""
    md = "{{skill: unfinished no close"
    markers = _find_markers(md)
    assert markers == []
