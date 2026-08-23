"""三语种 i18n 文件 schema 同步守护。

加新 key 必须三文件同时加，否则任意一文件缺失会让对应 locale 渲染回退。
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "i18n" / "data"
LOCALES = ("zh_CN", "zh_TW", "en_US", "vi_VN")

# directive 文案统一英文，t() 在 extract_prompts.py 硬编码 locale="en-US"——
# 单源放 en_US.json，translator 默认 fallback 兜底，其他 locale 不复制。
_DIRECTIVE_PREFIX = "i18n.extract.directive."


def _load_keys(locale: str) -> set[str]:
    return set(json.loads((DATA_DIR / f"{locale}.json").read_text()).keys())


def _non_directive_keys(keys: set[str]) -> set[str]:
    return {k for k in keys if not k.startswith(_DIRECTIVE_PREFIX)}


def test_all_locales_have_same_key_set():
    """四文件 key 集合完全相等（directive.* 单源 en_US 豁免）——加 key 必须四文件都加。"""
    loaded = {loc: _load_keys(loc) for loc in LOCALES}
    user_sets = {loc: _non_directive_keys(keys) for loc, keys in loaded.items()}
    reference_loc = LOCALES[0]
    reference = user_sets[reference_loc]
    for loc in LOCALES[1:]:
        missing = reference - user_sets[loc]
        extra = user_sets[loc] - reference
        assert not missing, f"{loc} 缺 key: {sorted(missing)}"
        assert not extra, f"{loc} 多 key: {sorted(extra)}"


def test_i18n_extract_directive_keys_match_lang_meta():
    """i18n.extract.directive.* 键集合 == _LANG_META 键集合（扫全部 JSON 文件不调函数）。"""
    from app.core.i18n.lang_meta import _LANG_META

    all_keys: set[str] = set()
    for loc in LOCALES:
        all_keys |= _load_keys(loc)
    expected = {f"{_DIRECTIVE_PREFIX}{lang}" for lang in _LANG_META}
    missing = expected - all_keys
    assert not missing, f"i18n.extract.directive.* 缺: {sorted(missing)}"


def test_directive_keys_only_in_en_us():
    """directive.* 单源 en_US.json——其他 locale 不复制（t() 写死 locale="en-US"）。

    若哪天 zh_CN/zh_TW/vi_VN 又出现 directive.*，说明重复引入，按本测试删。
    """
    for locale in ("zh_CN", "zh_TW", "vi_VN"):
        leaked = [k for k in _load_keys(locale) if k.startswith(_DIRECTIVE_PREFIX)]
        assert not leaked, f"{locale}.json 含应只在 en_US 的 directive keys: {leaked}"


def test_directive_values_no_format_placeholders():
    """directive 值不能含 `{` / `}`——`_EXTRACT_BASE.format()` 遇未注册占位符会 KeyError 炸 /extract。

    若未来 directive 想用 `{` 字面，加转义 `{{` 或换写法。
    """
    en_us = json.loads((DATA_DIR / "en_US.json").read_text())
    bad = []
    for key, value in en_us.items():
        if not key.startswith(_DIRECTIVE_PREFIX):
            continue
        if "{" in value or "}" in value:
            bad.append((key, value))
    assert not bad, f"directive 值含未转义花括号，会让 .format() 炸: {bad}"