"""system prompt 必须携带措辞约束：短口语问句、无问候铺垫、reason 要点化无前缀。"""
from __future__ import annotations

from app.domain.session import Session
from app.services.coaching.prompt import build_first_batch, build_system
from app.services.template.loader import get_template

_TPL = get_template("pm-research")


def test_recompute_system_carries_style_rule():
    system = build_system(_TPL, None)
    assert "≤20 字" in system
    assert "问候" in system          # 禁止问候铺垫
    assert "称呼" in system          # 禁称呼（如「彭经理，」）
    assert "≤15 字" in system
    assert "前缀" in system          # reason 不带「方向：/已明确：」前缀
    assert "编造" in system          # todo/new reason 不编造具体值
    assert "不要清空" in system       # 已有 reason 重算不清空
    assert "主题：" in system        # done 摘要带主题词
    assert "参考风格" in system      # 正向示例存在
    assert "1万元/年" in system      # done 示例只在会中重算出现


def test_recompute_system_bounds_new_and_orders():
    system = build_system(_TPL, None)
    assert "最多 2 条" in system     # 单次 status=new ≤2
    assert "发问顺序" in system      # 最该先问的排最前
    assert "必须给 reason" in system  # done 必须给摘要
    assert "措辞不同" in system      # 同义覆盖归并 done


def test_first_batch_system_carries_style_rule():
    system, _ = build_first_batch(_TPL, Session(id="s1", template_id="pm-research"))
    assert "≤20 字" in system
    assert "问候" in system
    assert "称呼" in system
    assert "≤15 字" in system
    assert "前缀" in system
    assert "编造" in system
    assert "尽量都给" in system      # todo/new reason 尽量填
    assert "参考风格" in system
    assert "可为空" in system        # todo reason 许可：可为空，填了写方向
    assert "1万元/年" not in system  # 首评全 todo，不带 done 示例
