"""报告悬空标签兜底：LLM 留空的「- 标签：」行机械补「本次访谈未提及」。"""
from __future__ import annotations

from app.services.reports.generator import _fill_dangling_labels


def test_fills_label_without_content():
    md = "## 机会与建议\n- 机会点 / 优先级建议：\n- 待验证假设：\n\n## 下一步"
    out = _fill_dangling_labels(md)
    assert "- 机会点 / 优先级建议： 本次访谈未提及" in out
    assert "- 待验证假设： 本次访谈未提及" in out


def test_keeps_inline_content():
    md = "- 痛点：售前记录易遗漏\n- 客户 / 行业：本次访谈未提及"
    assert _fill_dangling_labels(md) == md


def test_keeps_sub_bullet_form():
    md = "- 痛点：\n  - 售前记录易遗漏\n  - 笔记零散"
    assert _fill_dangling_labels(md) == md


def test_trailing_spaces_treated_as_empty():
    md = "- 机会点 / 优先级建议：  \n- 下一步："
    out = _fill_dangling_labels(md)
    assert out.count("本次访谈未提及") == 2


def test_plain_lines_untouched():
    md = "# 标题\n\n正文段落。\n\n- 正常条目"
    assert _fill_dangling_labels(md) == md
