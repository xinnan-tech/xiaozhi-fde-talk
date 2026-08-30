"""报告消毒：bleach 之后还原 `>` / `<` + 兜底删除 LLM 没填的占位符。

回归：
- `> ` 引用块在 bleach 之后是 `&gt;`；html.unescape 还原回 Markdown 语义。
- `<script>` 这种危险标签在 bleach 阶段就被剥掉，不会跟着 unescape 复活。
- LLM 偶尔留下 `{{ 内容 }}`（删了包装但忘了脱 `{{`/`}}`），自动清除；
  `{{skill: ...}}` 标记保留。
"""
from __future__ import annotations

from app.services.reports.generator import (
    _strip_orphan_placeholders,
    sanitize_report_markdown,
)


# --- sanitize_report_markdown ---

def test_blockquote_at_line_start_preserved():
    """`> 受访者：...` 通过消毒后仍是 `>` 开头，不变 `&gt;`。"""
    md = "# 标题\n> 受访者：彭经理　开始：2026-08-11"
    out = sanitize_report_markdown(md)
    assert "> 受访者：彭经理" in out
    assert "&gt;" not in out


def test_inline_lt_gt_preserved():
    """文本里的 `<` `>` 是普通字符，不应被转义。"""
    md = "i < 5 和 j > 3 的判断"
    out = sanitize_report_markdown(md)
    assert "i < 5" in out
    assert "j > 3" in out
    assert "&lt;" not in out
    assert "&gt;" not in out


def test_script_tag_still_stripped():
    """<script> 是 HTML 注入，bleach 阶段必须剥掉；unescape 不能再复活。"""
    md = "## 标题\n<script>alert(1)</script>\n正常文本"
    out = sanitize_report_markdown(md)
    assert "<script>" not in out
    assert "正常文本" in out


def test_img_onerror_stripped():
    """<img onerror=...> 的 onerror 属性必须被剥掉。"""
    out = sanitize_report_markdown('<img src=x onerror=alert(1)>')
    assert "onerror" not in out
    assert "<img" not in out


def test_markdown_table_em_passed_through():
    """Markdown 里 `<em>` 这种内联 HTML 标签（白名单）保留。"""
    md = "这是 <em>强调</em> 文本"
    out = sanitize_report_markdown(md)
    assert "<em>强调</em>" in out


# --- _strip_orphan_placeholders ---

def test_strip_orphan_simple():
    """`{{ ... }}` 整块清除（不含 `{{skill:...}}`）。"""
    md = "## 受访者\n- 客户行业：{{ 客户与行业标签 }}\n- 现状：{{ 现状描述 }}"
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "}}" not in out
    assert "客户行业" in out
    assert "现状" in out


def test_strip_preserves_skill_marker():
    """`{{skill: ...}}` 标记保留（含内部 `{{ }}` 也保留）。"""
    md = "看图：{{skill: flow, inputs: {\"title\":\"X\"}}}"
    out = _strip_orphan_placeholders(md)
    assert "{{skill: flow, inputs:" in out
    assert "}}" in out


def test_strip_preserves_session_marker():
    """`{{session.X}}` / `{session.X}` 都该被 strip（issue #122）。

    旧契约是「保留 session 占位符」，前提是 L1 预填一定能把 session 字段填进
    去——但 qwen-plus 等模型偶尔把 `{{session.start_time}}` 吞掉一个 `{` 后以
    单花括号形态写出，预填后这种形态不该再出现在 LLM 输出里；万一漏过来，再
    保留就等于把字面量落到报告。所以 session 不再是 exempt，遇到就 strip——
    后端兜底策略统一是「宁可空、不可见字面量」。
    """
    md = (
        "# {{session.project}}\n"
        "> 受访者：{{session.interviewee}}\n"
        "{{session.start_time}} — {{session.end_time}}\n"
        "开始：{session.start}　结束：{session.end}\n"
    )
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "{session" not in out


def test_strip_preserves_session_marker_mixed_with_orphan():
    """混合：session 占位符和普通 orphan 都清除。"""
    md = (
        "# {{session.project}}\n"
        "- 客户行业：{{ 客户与行业标签 }}\n"
        "- 受访者：{{session.interviewee}}\n"
    )
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "{{ 客户与行业标签 }}" not in out


def test_strip_handles_chinese():
    """长中文描述（含 + / ；）也能识别为占位符。"""
    md = "目标：{{ 优先支持iPad端离线转写+实时摘要生成；中文标点 }}"
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert "目标：" in out


def test_strip_preserves_completed_content():
    """已填好的内容（无 `{{ }}`）不变。"""
    md = "## 背景\n为提升欣南科技售前团队在客户访谈环节的专业性..."
    out = _strip_orphan_placeholders(md)
    assert out == md


def test_strip_multiple():
    """多个占位符都清除。"""
    md = "A {{ 1 }} B {{ 2 }} C {{ 3 }} D"
    out = _strip_orphan_placeholders(md)
    assert "{{" not in out
    assert out == "A  B  C  D"


# --- 集成：sanitize + strip 串联行为（端到端） ---

def test_end_to_end_realistic_garbage():
    """用户实际遇到的格式问题：bleach 转义 + LLM 残留占位符，串起来清干净。"""
    md = (
        "# 欣南科技售前 需求调研报告\n"
        "> 受访者：彭经理　开始：2026-08-11T15:31\n"
        "\n"
        "## 受访者与场景\n"
        "- 客户 / 行业：{{ 欣南科技（B2B企业服务类科技公司） }}\n"
        "- 现状：{{ 售前工作以现场拜访和远程会议为主 }}\n"
        "\n"
        "## 机会与建议\n"
        "{{ ① 首期聚焦实时转写 + 目标驱动问题提醒 }}\n"
    )
    out = sanitize_report_markdown(_strip_orphan_placeholders(md))
    assert "> 受访者：" in out
    assert "&gt;" not in out
    assert "{{" not in out
    assert "}}" not in out
    assert "欣南科技售前" in out
