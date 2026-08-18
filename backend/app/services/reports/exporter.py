"""报告导出：md / html / word。pdf 后加（需 weasyprint/pandoc）。

报告本就是 Markdown，导出是格式转换。
"""
from __future__ import annotations

import io

import bleach
import markdown

FORMATS = ("md", "html", "word")


class FormatNotImplementedError(NotImplementedError):
    """指定 format 暂未实现（如 pdf）。路由层捕获后返回结构化 501 JSON。"""
    def __init__(self, fmt: str):
        super().__init__(f"format {fmt!r} 未实现")
        self.fmt = fmt


_ALLOWED_TAGS = [
    "p", "br", "strong", "em", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "pre", "code", "h1", "h2", "h3", "h4", "blockquote", "a", "hr",
]
_ALLOWED_ATTRS = {"a": ["href"], "code": ["class"], "pre": ["class"]}


def _sanitize(html: str) -> str:
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


def export(md: str, fmt: str) -> tuple[bytes, str]:
    """Markdown → 指定格式，返回 (data, media_type)。"""
    fmt = (fmt or "md").lower()
    if fmt == "md":
        return md.encode("utf-8"), "text/markdown; charset=utf-8"
    if fmt == "html":
        body = markdown.markdown(md, extensions=["tables", "fenced_code"])
        body = _sanitize(body)
        page = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;}"
            "table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:4px 8px;}</style>"
            "</head><body>" + body + "</body></html>"
        )
        return page.encode("utf-8"), "text/html; charset=utf-8"
    if fmt == "word":
        return _to_docx(md), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    if fmt == "pdf":
        raise FormatNotImplementedError(fmt)
    raise ValueError(f"不支持的导出格式：{fmt}（可选 {FORMATS}）")


def _to_docx(md: str) -> bytes:
    """简易 Markdown → docx（标题/段落/列表/引用）。"""
    from docx import Document

    doc = Document()
    for line in md.splitlines():
        s = line.rstrip()
        if not s:
            continue
        if s.startswith("### "):
            doc.add_heading(s[4:].strip(), level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:].strip(), level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:].strip(), level=1)
        elif s.startswith("> "):
            doc.add_paragraph(s[2:].strip(), style="Intense Quote" if "Intense Quote" in [st.name for st in doc.styles] else None)
        elif s.startswith(("- ", "* ")):
            doc.add_paragraph(s[2:].strip(), style="List Bullet")
        else:
            doc.add_paragraph(s)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
