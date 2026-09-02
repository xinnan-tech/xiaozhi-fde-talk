"""MVP 内置 skill。

每个 skill 是一个 async(inputs: dict) -> SkillArtifact 函数，通过
register_skill(SkillDefinition(...)) 注册到 app.services.skill.registry。
"""
from __future__ import annotations

from app.services.skill.registry import SkillArtifact, SkillDefinition, register_skill


def _sanitize_inline(text: str) -> str:
    """单行 inline 上下文（标题 / 引用块首行 / 表头）用：折掉所有换行 / 回车成单行空格。"""
    # 统一换行符后再折叠，避免 CRLF / LF / CR 三种情况漏掉
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def _sanitize_blockquote_text(text: str) -> str:
    """把任意文本转成「每行都加 '> '」的引用块安全形式：保留空行作为段落分隔。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    # 空行用单个 '>' 保留段落分隔；非空行加 '> ' 前缀
    return "\n".join("> " + ln if ln else ">" for ln in lines)


def _escape_table_cell(value) -> str:
    """表格单元格转义：None → ''；'|' → '\\|'；换行 → '<br>'（GFM 表格内换行标准写法）。

    '<'br'>' 在 docx / html 导出链路里都按行内换行处理（GitHub 渲染亦同），
    比起裸 '\\n' 更安全——后者会让整张表在该单元格处断裂。
    """
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("|", "\\|")
    s = s.replace("\n", "<br>")
    return s


async def _echo(inputs: dict) -> SkillArtifact:
    title = _sanitize_inline(str(inputs.get("title") or "Skill 输出"))
    # 防级别提升：开头若有 '#'，把 '### title' 顶到更高级别甚至脱离标题上下文
    title = title.lstrip("#").lstrip() or "Skill 输出"
    content = _sanitize_inline(
        str(inputs.get("content") or inputs.get("text") or "（无输入内容）")
    )
    md = f"### {title}\n\n{content}"
    return SkillArtifact(mime="text/markdown", content=md, meta={"kind": "echo"})


async def _text_card(inputs: dict) -> SkillArtifact:
    title = _sanitize_inline(str(inputs.get("title") or "补充信息"))
    body = str(inputs.get("body") or inputs.get("content") or "本节暂无可展示内容。")
    # body 中含空行 / 换行时，每行都要带 '> ' 前缀才能留在 blockquote 里
    body_block = _sanitize_blockquote_text(body)
    md = f"> {title}\n>\n{body_block}"
    return SkillArtifact(mime="text/markdown", content=md, meta={"kind": "text-card"})


async def _markdown_table(inputs: dict) -> SkillArtifact:
    title = _sanitize_inline(str(inputs.get("title") or "表格"))
    columns = inputs.get("columns") or ["项目", "内容"]
    rows = inputs.get("rows") or []
    if not isinstance(columns, list) or not columns:
        columns = ["项目", "内容"]
    if not isinstance(rows, list):
        rows = []
    warnings: list[str] = []
    n_cols = len(columns)
    header_cells = [_escape_table_cell(c) for c in columns]
    header = "| " + " | ".join(header_cells) + " |"
    sep = "| " + " | ".join("---" for _ in range(n_cols)) + " |"
    body = []
    for idx, row in enumerate(rows):
        if isinstance(row, dict):
            cells = [row.get(c, "") for c in columns]
        elif isinstance(row, list):
            cells = list(row)
        else:
            cells = [row]
        if len(cells) > n_cols:
            warnings.append(
                f"row {idx}: got {len(cells)} cells, expected {n_cols}; "
                f"trailing {len(cells) - n_cols} dropped"
            )
            cells = cells[:n_cols]
        elif len(cells) < n_cols:
            cells = list(cells) + [""] * (n_cols - len(cells))
        body.append("| " + " | ".join(_escape_table_cell(c) for c in cells) + " |")
    if not body:
        body.append("| " + " | ".join("待补充" for _ in range(n_cols)) + " |")
    meta: dict = {"kind": "markdown-table"}
    if warnings:
        meta["warnings"] = warnings
    return SkillArtifact(
        mime="text/markdown",
        content="\n".join([f"### {title}", "", header, sep, *body]),
        meta=meta,
    )


register_skill(
    SkillDefinition(
        id="echo",
        name="回显文本",
        description="把输入内容作为 Markdown 小节嵌入报告，用于联调 skill 标记替换。",
        handler=_echo,
        input_schema={"title": "string", "content": "string"},
    )
)

register_skill(
    SkillDefinition(
        id="text-card",
        name="文本卡片",
        description="把输入内容渲染为 Markdown 引用块。",
        handler=_text_card,
        input_schema={"title": "string", "body": "string"},
    )
)

register_skill(
    SkillDefinition(
        id="markdown-table",
        name="Markdown 表格",
        description="把 columns 和 rows 渲染为 Markdown 表格。",
        handler=_markdown_table,
        input_schema={"title": "string", "columns": "list[string]", "rows": "list[list|string|dict]"},
    )
)