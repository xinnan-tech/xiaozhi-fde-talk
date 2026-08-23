"""extract prompt：单一英文 base + 参数化指令（_EXTRACT_DIRECTIVES 模块字典）。"""
from __future__ import annotations

import re

from app.core.i18n.extract_prompts import build_extract_system, _extract_directive
from app.core.i18n.lang_meta import _LANG_META


def test_directive_zh_cn_chinese():
    """zh_cn 偏好 → 指令含 '简体中文' 与 'Simplified Chinese'。"""
    d = _extract_directive("zh_cn")
    assert "简体中文" in d
    assert "Simplified Chinese" in d


def test_directive_en():
    """en 偏好 → 指令为英文。"""
    d = _extract_directive("en")
    assert "English" in d
    assert "翻译" not in d


def test_directive_unknown_lang_falls_back_to_en():
    """未知 lang → 走 en 兜底（与 _LANG_META 一致）。"""
    d = _extract_directive("xx_unknown")
    assert "English" in d


def test_build_extract_system_injects_all_placeholders():
    out = build_extract_system(
        "en",
        today="2026-08-20",
        current_values="(empty)",
        transcript="客户是 ABC 公司 CEO 张三",
        fields=["name", "company"],
    )
    assert "English" in out
    assert "2026-08-20" in out
    assert "(empty)" in out
    assert "客户是 ABC 公司 CEO 张三" in out
    assert "name" in out and "company" in out


def test_build_extract_system_default_lang_zh_cn():
    out = build_extract_system(
        today="2026-08-20",
        current_values="",
        transcript="",
        fields=[],
    )
    assert "简体中文" in out


def test_build_extract_system_base_part_no_cjk():
    """剥离 directive 后 base 部分应不含中文（CJK 统一表意文字 U+4E00–U+9FFF）。"""
    out = build_extract_system(
        "zh_cn",
        today="2026-08-20",
        current_values="",
        transcript="",
        fields=["name"],
    )
    directive = _extract_directive("zh_cn")
    base_part = out.replace(directive, "")
    cjk = re.findall(r"[一-鿿]", base_part)
    assert not cjk, f"base 含中文字符：{cjk[:5]}"


def test_directive_keys_match_lang_meta():
    """_EXTRACT_DIRECTIVES 键集合 == _LANG_META 键集合——加语种必须双边改。"""
    from app.core.i18n.extract_prompts import _EXTRACT_DIRECTIVES

    missing = set(_LANG_META) - set(_EXTRACT_DIRECTIVES)
    extra = set(_EXTRACT_DIRECTIVES) - set(_LANG_META)
    assert not missing, f"_EXTRACT_DIRECTIVES 缺: {sorted(missing)}"
    assert not extra, f"_EXTRACT_DIRECTIVES 多: {sorted(extra)}"
    for lang in _LANG_META:
        text = _EXTRACT_DIRECTIVES[lang]
        assert text, f"_EXTRACT_DIRECTIVES[{lang}] 文案为空"
