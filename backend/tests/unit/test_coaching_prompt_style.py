"""system prompt 必须携带措辞约束：短问句、无问候铺垫、reason 要点化无前缀。

Stage 3 单一英文 base 后断言改为英文措辞——约束语义不变。
"""
from __future__ import annotations

from app.domain.session import Session
from app.services.coaching.prompt import build_first_batch, build_system
from app.services.template.loader import get_template

def _tpl():
    # 模板 DB 化后须惰性取：模块级取值发生在 collection 期，早于 warm fixture，
    # 此时缓存还是空的（get_template 返回 None）
    return get_template("pm-research")


def test_recompute_system_carries_style_rule():
    system = build_system(_tpl(), None)
    assert "~20 words" in system          # 短问句约束
    assert "honorifics" in system          # 禁止 honorifics / greetings
    assert "greetings" in system          # 禁止 greetings
    assert "thanks" in system             # 禁止 thanks
    assert "≤15 words" in system          # reason 字数约束
    assert "prefixes like" in system       # reason 不带 "Direction:" 等前缀
    assert "made-up specifics" in system   # todo/new reason 不编造具体值
    assert "10K RMB/year" in system        # done 示例只在会中重算出现
    assert "Reference style" in system     # 正向示例存在
    assert "topic: conclusion" in system    # done reason 主题: 结论 格式


def test_recompute_system_bounds_new_and_orders():
    system = build_system(_tpl(), None)
    assert "at most 2" in system           # 单次 status=new ≤2
    assert "interview order" in system     # 最该先问的排最前
    assert "MUST give" in system           # done 必须给 reason
    assert "phrased differently" in system # 同义覆盖归并 done


def test_first_batch_system_carries_style_rule():
    system, _ = build_first_batch(_tpl(), Session(id="s1", template_id="pm-research"))
    assert "~20 words" in system
    assert "honorifics" in system
    assert "≤15 words" in system
    assert "prefixes like" in system
    assert "made-up specifics" in system
    assert "Reference style" in system
    assert "10K RMB/year" not in system    # 首评全 todo，不带 done 示例


def test_first_batch_injects_native_name_into_output_language_section():
    """zh_cn first_batch system 含 `## Output language (简体中文, mandatory)`。"""
    system, _ = build_first_batch(_tpl(), Session(id="s1", template_id="pm-research"), "zh_cn")
    assert "## Output language (简体中文, mandatory)" in system


def test_en_first_batch_injects_english_native_name():
    """en first_batch system 含 `## Output language (English, mandatory)`。"""
    system, _ = build_first_batch(_tpl(), Session(id="s1", template_id="pm-research"), "en")
    assert "## Output language (English, mandatory)" in system


def test_vi_first_batch_injects_vietnamese_native_name():
    """vi first_batch system 含越南语 native name。"""
    system, _ = build_first_batch(_tpl(), Session(id="s1", template_id="pm-research"), "vi")
    assert "Tiếng Việt" in system


def test_every_lang_recompute_injects_native_name():
    """每种语种 recompute system 注入对应 native_name。"""
    from app.core.i18n.lang_meta import _LANG_META
    for lang, meta in _LANG_META.items():
        system = build_system(_tpl(), None, lang)
        assert meta.native_name in system, (
            f"recompute {lang} system 未注入 {meta.native_name!r}"
        )