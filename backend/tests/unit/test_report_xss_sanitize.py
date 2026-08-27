"""· 报告 Markdown XSS 消毒（M-005）。

generate_report 直接返回 LLM 生成的 Markdown，前端渲染为 HTML 时若含 <script> /
事件处理器等存在 XSS。返回前用 bleach 消毒：strip=True 移除非白名单标签（含其
属性），保留安全 Markdown 语法与白名单内标签。

注：strip=True 会保留被剥离标签的纯文本子节点（如 <script>alert</script> →
alert），这是无害文本、不可执行；安全不变量是「无存活活动标签/事件处理器」。
"""
from __future__ import annotations

from app.services.reports.generator import sanitize_report_markdown


def test_strips_script_tags():
    md = "# Report\n<script>alert('xss')</script>\ncontent"
    safe = sanitize_report_markdown(md)
    assert "<script>" not in safe
    assert "</script>" not in safe
    assert "content" in safe  # 正文保留


def test_strips_event_handlers():
    md = "# Report\n<img src=x onerror=alert(1)>"
    safe = sanitize_report_markdown(md)
    assert "<img" not in safe
    assert "onerror" not in safe


def test_strips_style_and_iframe():
    md = "<style>body{}</style><iframe src=evil></iframe>"
    safe = sanitize_report_markdown(md)
    assert "<style" not in safe and "<iframe" not in safe


def test_preserves_safe_markdown():
    md = "# Title\n- item 1\n- item 2\n**bold** and `code`"
    safe = sanitize_report_markdown(md)
    assert "# Title" in safe
    assert "**bold**" in safe
    assert "`code`" in safe


def test_preserves_allowed_link():
    md = "[repo](https://example.com)"
    safe = sanitize_report_markdown(md)
    assert "https://example.com" in safe
