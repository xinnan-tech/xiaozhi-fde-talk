from __future__ import annotations
from app.services.reports.exporter import export


def test_html_strips_script_tag():
    md = "报告\n\n<script>alert(1)</script>\n\n正常文本"
    data, _ = export(md, "html")
    html = data.decode("utf-8")
    assert "<script>" not in html
    # bleach 的 strip=True 移除 <script> 标签（执行上下文），其文本内容
    # "alert(1)" 作为纯文本保留——纯文本不会执行，非 XSS 向量。真正的
    # 安全属性是 <script> 标签消失，由上一行断言保证。
    assert "正常文本" in html


def test_html_keeps_tables_and_code():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    data, _ = export(md, "html")
    assert "<table>" in data.decode("utf-8")


def test_html_strips_javascript_link():
    md = "[x](javascript:alert(1))"
    data, _ = export(md, "html")
    html = data.decode("utf-8")
    assert "javascript:" not in html
    assert "alert" not in html


def test_html_strips_img_onerror():
    md = "<img src=x onerror=alert(1)>"
    data, _ = export(md, "html")
    html = data.decode("utf-8")
    assert "onerror" not in html
