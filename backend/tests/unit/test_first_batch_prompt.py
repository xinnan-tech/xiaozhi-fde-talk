"""build_first_batch：system 含 base context + Output language 段；user 含 base_info/基线。

Stage 3 单一英文 base 后断言改为英文措辞。约束语义不变。
"""
from __future__ import annotations

from app.domain.session import Session
from app.services.coaching.prompt import build_first_batch
from app.services.template.loader import get_template


def _session() -> Session:
    return Session(
        id="s1", template_id="pm-research",
        base_info={"project": "零售<POS>", "interviewee": "王经理"},
        goal="搞清库存痛点 & 目标",
    )


def test_first_batch_contents():
    system, user = build_first_batch(get_template("pm-research"), _session())
    assert "product manager" in system     # English description of interviewee's role
    assert "搞清库存痛点 &amp; 目标" in system  # goal 转义保留在 user_* 标签里（中文 metadata verbatim）
    assert "零售&lt;POS&gt;" in user       # base_info 转义
    assert '"id": "objective"' in user    # 基线带稳定 id
    assert "opening batch" in system       # first-batch prompt 标题


def test_first_batch_empty_inputs():
    s = Session(id="s2", template_id="pm-research")
    system, user = build_first_batch(get_template("pm-research"), s)
    assert "<user_goal>" not in system    # 无 goal 不留空块
    assert "{}" in user                   # 空 base_info 也能组出合法 JSON


def test_first_batch_system_includes_user_tags_promise():
    """system 明确告诉 LLM `<user_*>` blocks 可能含中文——single-turn 翻译提示。"""
    system, _ = build_first_batch(get_template("pm-research"), _session())
    assert "<user_*>" in system or "<user_base_info>" in system


def test_first_batch_system_includes_json_shape_example():
    """system 包含 JSON 结构示例——LLM 学两步流程（中文 baseline → 目标语言 JSON）。"""
    system, _ = build_first_batch(get_template("pm-research"), _session())
    assert "## Example" in system
    assert "{lang_native}" not in system  # 占位符必须已被替换
    assert "{lang_english}" not in system
    assert "{lang_bcp47}" not in system