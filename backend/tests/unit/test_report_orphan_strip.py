"""报告 orphan 占位符兜底：双花括号 / 单花括号 `{session.X}` 都该被清除。

回归 issue #122：qwen-plus 偶尔把 `{{session.start_time}}` 吞掉一个 `{` 后
以 `{session.start}` 单花括号形态写出，落到 `content_md` 里就成字面量。修
复后 `_strip_orphan_placeholders` 必须把单花括号 `session.X` 一并清掉。
"""
from __future__ import annotations

from app.services.reports.generator import _strip_orphan_placeholders


def test_strip_double_curly_orphan():
    md = "before {{ 标题 }} after"
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "标题" not in out
    assert "before  after" in out


def test_strip_double_curly_session_orphan():
    """{{session.X}} 不该再豁免——L1 预填后这两种形态都不该出现在 LLM 输出。"""
    md = "> 受访者：{{session.interviewee}}　开始：{{session.start_time}}"
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "{{session" not in out


def test_strip_single_curly_session_orphan():
    """回归 issue #122 核心场景：`{session.start}` 字面量被清除。"""
    md = "> 受访者：张三　开始：{session.start}　结束：{session.end}"
    out = _strip_orphan_placeholders(md)
    assert "{session" not in out
    assert "受访者：张三" in out
    assert "开始：　结束：" in out


def test_strip_mixed_double_and_single_curly_session_orphans():
    md = (
        "# Title\n"
        "> 受访者：{{session.interviewee}}　开始：{session.start}\n\n"
        "{{ 中文提示 }}\n"
    )
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "{session" not in out


def test_strip_preserves_skill_markers():
    """`{{skill: ...}}` 必须保留——_find_markers 后续要识别。"""
    md = "before {{skill: echo, inputs: {\"x\": 1}}} after"
    out = _strip_orphan_placeholders(md)
    assert "{{skill: echo" in out
    assert "{{skill:" in out


def test_strip_preserves_plain_curly_text():
    """markdown 普通 `{...}` 文本（不像 session 字段名）不该被误吞。"""
    md = "use {foo} or {bar} for placeholder"
    out = _strip_orphan_placeholders(md)
    # 不是 session.X 形态 → 不动
    assert "{foo}" in out
    assert "{bar}" in out