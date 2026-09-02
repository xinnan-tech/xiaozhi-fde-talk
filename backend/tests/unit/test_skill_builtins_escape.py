"""内置 skill 转义测试：覆盖 markdown-table / text-card / echo 的 Markdown 注入场景。

对应 issue #194：LLM 填充 inputs 时常出现 '|'、换行、null；之前直接 f-string 拼进
Markdown，导致表格错位、引用块逃逸、标题级别被顶高等问题。
"""
from __future__ import annotations

import asyncio

from app.services.skill.builtins import _echo, _markdown_table, _text_card


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------- echo ----------

def test_echo_basic():
    art = _run(_echo({"title": "T", "content": "hi"}))
    assert art.content == "### T\n\nhi"


def test_echo_title_newline_collapsed():
    """title 带换行必须被折成单行，不能注入新结构。"""
    art = _run(_echo({"title": "H\n# Injected", "content": "x"}))
    # 整个 title 必须在同一行；不应出现独立的 '# Injected' 行
    assert art.content.startswith("### H # Injected\n\nx")
    assert "\n# Injected" not in art.content


def test_echo_title_strip_leading_hashes():
    """title 开头带 '#' 防止 '### ### X' 双前缀引起渲染歧义。"""
    art = _run(_echo({"title": "### Pwned", "content": "x"}))
    # lstrip('#') 后 '### Pwned' → 'Pwned'；最终只有 skill 自己加的 '### '
    assert art.content == "### Pwned\n\nx"
    # 不应出现双重 '###' 前缀
    assert "### ### " not in art.content


def test_echo_content_newline_collapsed():
    """content 带换行也要折成单行（echo 语义是 inline 段落）。"""
    art = _run(_echo({"title": "T", "content": "line1\nline2"}))
    assert art.content == "### T\n\nline1 line2"


def test_echo_defaults_when_missing():
    art = _run(_echo({}))
    assert art.content == "### Skill 输出\n\n（无输入内容）"


# ---------- text-card ----------

def test_text_card_basic():
    art = _run(_text_card({"title": "X", "body": "para1"}))
    assert art.content == "> X\n>\n> para1"


def test_text_card_body_paragraph_breaks_stay_in_quote():
    """body 含空行（段落分隔）必须仍留在 blockquote 内。"""
    art = _run(_text_card({"title": "X", "body": "para1\n\npara2"}))
    # 关键：para2 必须在 '> ' 前缀下，不能裸出来
    assert art.content == "> X\n>\n> para1\n>\n> para2"
    # 防御：连续两行不全是 '> ' / '>'，说明逃出引用块了
    for line in art.content.splitlines():
        assert line.startswith(">"), f"line escaped blockquote: {line!r}"


def test_text_card_body_single_newline():
    art = _run(_text_card({"title": "X", "body": "a\nb"}))
    assert art.content == "> X\n>\n> a\n> b"


def test_text_card_title_newline_collapsed():
    art = _run(_text_card({"title": "X\nY", "body": "b"}))
    # title 折成单行
    assert art.content.startswith("> X Y\n")


def test_text_card_defaults():
    art = _run(_text_card({}))
    # 默认 body 文案
    assert "> 本节暂无可展示内容。" in art.content


# ---------- markdown-table ----------

def test_markdown_table_basic():
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [["x", "y"], ["z", "w"]],
    }))
    assert art.content == "### T\n\n| a | b |\n| --- | --- |\n| x | y |\n| z | w |"


def test_markdown_table_escapes_pipe_in_cell():
    """单元格里的 '|' 必须转义，否则会多切列。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [["x|y", "ok"]],
    }))
    assert "\\|" in art.content
    # 实际表头/分隔/行数仍正确：1 个 header + 1 sep + 1 data 行
    rows = art.content.splitlines()
    assert rows[0] == "### T"
    assert rows[1] == ""
    assert rows[2] == "| a | b |"
    assert rows[3] == "| --- | --- |"
    assert rows[4] == "| x\\|y | ok |"


def test_markdown_table_newline_in_cell():
    """换行 → '<br>'，不能裸 \\n（否则表格在该行断裂）。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [["x", "p\nq"]],
    }))
    # 单元格内容里不含裸 \n（除了由 <br> 之外的字符）
    # 内容里 'p\nq' 应被替换为 'p<br>q'
    assert "p<br>q" in art.content
    # 行结构仍是 1 个 data 行
    assert art.content.count("\n") == 4  # 5 行 = 4 个换行


def test_markdown_table_none_cell_becomes_empty():
    """None 单元格不应渲染成 'None' 字面量。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [[None, "ok"]],
    }))
    assert "None" not in art.content
    assert "|  | ok |" in art.content


def test_markdown_table_short_row_padded():
    """cells 不足时补空字符串。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b", "c"],
        "rows": [["x", "y"]],  # 缺一个
    }))
    assert "| x | y |  |" in art.content
    # 不该 warn（是 padded，不是 truncate）
    assert art.meta.get("warnings") is None


def test_markdown_table_extra_cells_warn():
    """cells 多于列数时静默截断是 bug；这里应在 meta 里加 warning。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a"],  # 只 1 列
        "rows": [["x", "y", "z", "w"]],  # 4 个
    }))
    # 多余被截掉
    assert art.content.endswith("| x |")
    # warning 写进 meta
    warnings = art.meta.get("warnings") or []
    assert any("dropped" in w for w in warnings), f"expected dropped warning, got {warnings}"


def test_markdown_table_empty_rows_placeholder():
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [],
    }))
    assert "| 待补充 | 待补充 |" in art.content


def test_markdown_table_dict_row():
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a", "b"],
        "rows": [{"a": "x", "b": "y"}],
    }))
    assert "| x | y |" in art.content


def test_markdown_table_columns_escaped():
    """列名里如果带 '|' / 换行 / None 也要转义。"""
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a|b", None],
        "rows": [["x", "y"]],
    }))
    # 'a|b' → 'a\|b'；None → ''
    assert art.content.startswith("### T\n\n| a\\|b |  |\n| --- | --- |\n| x | y |")


def test_markdown_table_backslash_escaped_first():
    """'\\' 必须先于 '|' 转义：'\\|' → '\\\\\\|'（最终 Markdown 渲染回 '\\|'）。

    顺序反了会怎样？先 | → \\|：输入 \\| → \\\\\\| （4 字符），Markdown 解析
    '\\\\' 被吃掉变 '\\'，剩下 '|' 被识别为列分隔符——表格照裂。
    """
    art = _run(_markdown_table({
        "title": "T",
        "columns": ["a"],
        "rows": [["\\|"]],  # 用户输入 \|（2 字符）
    }))
    # 完整 data 行应是 '| \\\| |' (8 字符：|, space, 3 backslashes, |, space, |)
    # 直接断言 escape 输出字符序列：
    # 输入 \| → escape → \\\| (4 字符)
    assert "\\\\\\|" in art.content
    # 反例：如果漏掉反斜杠转义，data 行会是 '| \| |'，被 Markdown 解析时 \| 又变回 |
    # 整个 content 里 \\ 出现 3 次（输入 1 个 \ 变 3 个 \），| 出现 4 次（| a | 外壳 + | 单元 | 外壳）
    # ——这里只验关键子序列，避免脆数


def test_markdown_table_double_backslash_preserved():
    """'\\\\' 应转义为 '\\\\\\\\'，Markdown 渲染回 '\\\\'。"""
    from app.services.skill.builtins import _escape_table_cell
    # 输入 \\ (2 字符) → 转义 → \\\\ (4 字符)
    assert _escape_table_cell("\\\\") == "\\\\\\\\"


def test_markdown_table_pipe_with_backslash_roundtrip():
    """直接调 escape 函数验证 round-trip：原意 \\| 在渲染后仍是 \\|。"""
    from app.services.skill.builtins import _escape_table_cell
    # 输入 \"\\|\"（一个反斜杠 + 一个竖线，2 字符）→ 应输出 '\\\\\\|'（4 字符）
    assert _escape_table_cell("\\|") == "\\\\\\|"
    # 输入单个 '|'
    assert _escape_table_cell("|") == "\\|"
    # 输入 '\\\\'
    assert _escape_table_cell("\\\\") == "\\\\\\\\"
    # 顺序敏感性：先转 | 再转 \ 会得到错的 '\\\\|'（4 字符），正确是 '\\\\\\|'（4 字符含一个 |）
    # 直接断言两者的差异以锁死顺序
    bad_order = "\\|".replace("|", "\\|").replace("\\", "\\\\")
    good_order = "\\|".replace("\\", "\\\\").replace("|", "\\|")
    assert good_order != bad_order  # 顺序敏感，回归保护
    assert _escape_table_cell("\\|") == good_order