"""MVP 内置 skill。

每个 skill 是一个 async(inputs: dict) -> SkillArtifact 函数，通过
register_skill(SkillDefinition(...)) 注册到 app.services.skill.registry。
"""
from __future__ import annotations

from app.services.skill.registry import SkillArtifact, SkillDefinition, register_skill


async def _echo(inputs: dict) -> SkillArtifact:
    title = str(inputs.get("title") or "Skill 输出")
    content = str(inputs.get("content") or inputs.get("text") or "（无输入内容）")
    md = f"### {title}\n\n{content}"
    return SkillArtifact(mime="text/markdown", content=md, meta={"kind": "echo"})


async def _text_card(inputs: dict) -> SkillArtifact:
    title = str(inputs.get("title") or "补充信息")
    body = str(inputs.get("body") or inputs.get("content") or "本节暂无可展示内容。")
    md = f"> {title}\n>\n> {body}"
    return SkillArtifact(mime="text/markdown", content=md, meta={"kind": "text-card"})


async def _markdown_table(inputs: dict) -> SkillArtifact:
    title = str(inputs.get("title") or "表格")
    columns = inputs.get("columns") or ["项目", "内容"]
    rows = inputs.get("rows") or []
    if not isinstance(columns, list) or not columns:
        columns = ["项目", "内容"]
    if not isinstance(rows, list):
        rows = []
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        if isinstance(row, dict):
            cells = [row.get(c, "") for c in columns]
        elif isinstance(row, list):
            cells = row
        else:
            cells = [row]
        padded = list(cells)[: len(columns)] + [""] * max(0, len(columns) - len(cells))
        body.append("| " + " | ".join(str(c) for c in padded) + " |")
    if not body:
        body.append("| " + " | ".join("待补充" for _ in columns) + " |")
    return SkillArtifact(
        mime="text/markdown",
        content="\n".join([f"### {title}", "", header, sep, *body]),
        meta={"kind": "markdown-table"},
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
