"""报告 prompt：单一英文 base 的硬约束必须保留，防止弱化。

回归需求：把 _REPORT_SYSTEM 里的语言中立结构约束断言下来——LLM 是否仍按
两步式 + 占位符规则 + EXEMPT 类别输出，取决于 base 本身。
"""
import re

from app.core.i18n.lang_meta import _LANG_META
from app.services.reports.generator import (
    _FALLBACK_BY_LANG,
    _REPORT_SYSTEM,
    _report_system,
)


def test_en_system_demands_full_english():
    """en 模式 system 必须强制 ENTIRE 全文英文——防止 base 弱化后 LLM 漏写。"""
    body = _report_system("en").lower()
    assert "entire" in body, f"en system 未约束 ENTIRE：{body[:300]!r}"


def test_en_system_provides_fallback_phrase():
    body = _report_system("en")
    assert _FALLBACK_BY_LANG["en"] in body, (
        f"en system 未内嵌兜底短语 {_FALLBACK_BY_LANG['en']!r}——后处理注入中文风险"
    )


def test_base_uses_chinese_scaffolding_as_structural_only():
    """base 必须把中文骨架声明为「先翻译成目标语种再填内容」。

    修复 ce645969-bfb4-47a4-b327-89502a44f6f7 实证 bug：中文 base + 中文骨架 +
    中文转写下 qwen-plus 完全镜像中文。改两步式后 base 必须显式承认 base 是中文骨架
    （"written in Chinese"），并要求翻译后再填（"translate" / "translated skeleton"）。
    few-shot 示例把两步过程走一遍让 LLM 走 in-context 而不是听尾部 directive。

    用正则确保三件事实同时出现：
    - "chinese"（承认 base / skeleton 是中文）
    - "skeleton"（指向骨架本体——两步式的核心对象）
    - "translate"（要求翻译骨架）
    反向：禁止偷渡成"do not" / "don't translate"否定形式。
    """
    body = _REPORT_SYSTEM.lower()
    pos_pattern = re.compile(
        r"\bchinese\b[\s\S]{0,300}?\bskeleton\b[\s\S]{0,300}?(?<!do not )(?<!don't )\btranslat\w*\b"
    )
    assert pos_pattern.search(body), (
        f"base 未把中文骨架声明为「待翻译」——qwen-plus 会镜像中文：{body[:300]!r}"
    )
    # 反向：禁止"do not / don't ... translate ... chinese ... skeleton"否定形式。
    assert not re.search(
        r"\b(?:do\s+not|don't|do\s+n't)\b[\s\S]{0,80}?\btranslat\w*\b[\s\S]{0,80}?\bchinese\b[\s\S]{0,80}?\bskeleton\b",
        body,
    ), (
        f"base 被偷渡成「do not translate ... chinese ... skeleton」否定形式——两步式策略被破坏"
    )


def test_base_instructs_placeholder_wrapper_deletion():
    """base 必须显式要求 LLM 删除 {{ }} 包装——结构但语言中立规则。"""
    body = _REPORT_SYSTEM.lower()
    has_delete_phrase = (
        "delete both the `{{` and `}}` markers" in body
        or "delete the `{{` and `}}` wrappers" in body
    )
    assert has_delete_phrase, (
        f"base 未显式要求删除 {{ }} 包装：{body[:300]!r}"
    )


def test_base_enumerates_exempt_placeholders():
    """base 必须列出 EXEMPT 类别（session.X / skill:）——保护两类占位符不被误删。"""
    body = _REPORT_SYSTEM.lower()
    assert "exempt" in body, f"base 未明确豁免占位符列表：{body[:300]!r}"
    assert "{{session.x}}" in body or "session.x" in body, (
        f"base 未点名 {{session.X}} 豁免：{body[:300]!r}"
    )
    assert "skill:" in body, f"base 未点名 skill 豁免：{body[:300]!r}"


def test_base_preserves_placeholder_and_skill_rules():
    """占位符与 skill 标记规则对所有语种通用，base 必须包含。"""
    body = _REPORT_SYSTEM
    assert "{{session.X}}" in body or "session.X" in body, (
        f"base 未保留 session 占位规则：{body[:300]!r}"
    )
    assert "skill:" in body, f"base 未保留 skill 标记规则：{body[:300]!r}"


# --- 跨 dict 不变量：兜底短语键集合必须等于 _LANG_META 键集合 ---


def test_fallback_keys_match_lang_meta():
    """兜底短语键集合 ⊆ _LANG_META——派生约束，import 期 assert 已保底。"""
    assert set(_FALLBACK_BY_LANG) == set(_LANG_META), (
        f"兜底短语键集合必须等于 _LANG_META 键集合："
        f"{set(_FALLBACK_BY_LANG) ^ set(_LANG_META)}"
    )


# --- 参数化注入：每种语种 system 都含 _FALLBACK_BY_LANG[lang] ---


def test_every_lang_system_includes_its_fallback_phrase():
    """每条 _FALLBACK_BY_LANG[lang] 必须出现在 _report_system(lang) 里——LLM 与后处理
    共用同一短语，避免 EN 报告被 deterministic 兜底注入中文。"""
    for lang in _LANG_META:
        body = _report_system(lang)
        assert _FALLBACK_BY_LANG[lang] in body, (
            f"语种 {lang!r} 的 system 未内嵌兜底短语 {_FALLBACK_BY_LANG[lang]!r}"
        )


def test_every_lang_system_injects_its_native_name():
    """每条 _LANG_META[lang].native_name 必须出现在 _report_system(lang) 里——LLM
    据此知道输出语种。"""
    for lang, meta in _LANG_META.items():
        body = _report_system(lang)
        assert meta.native_name in body, (
            f"语种 {lang!r} 的 system 未注入 native_name {meta.native_name!r}"
        )