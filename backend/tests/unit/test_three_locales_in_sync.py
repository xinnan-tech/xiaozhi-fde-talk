"""三语种 i18n 文件 schema 同步守护。

加新 key 必须三文件同时加，否则任意一文件缺失会让对应 locale 渲染回退。
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "i18n" / "data"
LOCALES = ("zh_CN", "zh_TW", "en_US")

# directive 文案统一英文，t() 在 extract_prompts.py 硬编码 locale="en-US"——
# 单源放 en_US.json，translator 默认 fallback 兜底，其他 locale 不复制。
_DIRECTIVE_PREFIX = "i18n.extract.directive."


def _load_keys(locale: str) -> set[str]:
    return set(json.loads((DATA_DIR / f"{locale}.json").read_text()).keys())


def _non_directive_keys(keys: set[str]) -> set[str]:
    return {k for k in keys if not k.startswith(_DIRECTIVE_PREFIX)}


def test_three_locales_have_same_key_set():
    """三文件 key 集合完全相等（directive.* 单源 en_US 豁免）——加 key 必须三文件都加。"""
    zh_cn = _load_keys("zh_CN")
    zh_tw = _load_keys("zh_TW")
    en_us = _load_keys("en_US")

    zh_cn_user = _non_directive_keys(zh_cn)
    zh_tw_user = _non_directive_keys(zh_tw)
    en_us_user = _non_directive_keys(en_us)

    missing_in_zh_tw = zh_cn_user - zh_tw_user
    missing_in_en_us = zh_cn_user - en_us_user
    extra_in_zh_tw = zh_tw_user - zh_cn_user
    extra_in_en_us = en_us_user - zh_cn_user

    assert not missing_in_zh_tw, f"zh_TW 缺 key: {sorted(missing_in_zh_tw)}"
    assert not missing_in_en_us, f"en_US 缺 key: {sorted(missing_in_en_us)}"
    assert not extra_in_zh_tw, f"zh_TW 多 key: {sorted(extra_in_zh_tw)}"
    assert not extra_in_en_us, f"en_US 多 key: {sorted(extra_in_en_us)}"


def test_i18n_extract_directive_keys_match_lang_meta():
    """i18n.extract.directive.* 键集合 == _LANG_META 键集合（扫三 JSON 文件不调函数）。"""
    from app.core.i18n.lang_meta import _LANG_META

    all_keys = _load_keys("zh_CN") | _load_keys("zh_TW") | _load_keys("en_US")
    expected = {f"{_DIRECTIVE_PREFIX}{lang}" for lang in _LANG_META}
    missing = expected - all_keys
    assert not missing, f"i18n.extract.directive.* 缺: {sorted(missing)}"


def test_directive_keys_only_in_en_us():
    """directive.* 单源 en_US.json——zh_CN/zh_TW 不复制（t() 写死 locale="en-US"）。

    若哪天 zh_CN/zh_TW 又出现 directive.*，说明重复引入，按本测试删。
    """
    for locale in ("zh_CN", "zh_TW"):
        leaked = [k for k in _load_keys(locale) if k.startswith(_DIRECTIVE_PREFIX)]
        assert not leaked, f"{locale}.json 含应只在 en_US 的 directive keys: {leaked}"