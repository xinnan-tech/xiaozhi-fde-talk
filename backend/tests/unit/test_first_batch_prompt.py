"""build_first_batch：system 含 playbook/goal，user 含 base_info/基线，输入均转义。"""
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
    assert "产品经理" in system            # playbook 注入
    assert "搞清库存痛点 &amp; 目标" in system  # goal 转义
    assert "零售&lt;POS&gt;" in user       # base_info 转义
    assert '"id": "objective"' in user    # 基线带稳定 id
    assert "尚" in system and "第一批" in system


def test_first_batch_empty_inputs():
    s = Session(id="s2", template_id="pm-research")
    system, user = build_first_batch(get_template("pm-research"), s)
    assert "<user_goal>" not in system    # 无 goal 不留空块
    assert "{}" in user                   # 空 base_info 也能组出合法 JSON
