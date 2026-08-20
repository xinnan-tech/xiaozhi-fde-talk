"""三语种 i18n 文件 schema 同步守护。

加新 key 必须三文件同时加，否则任意一文件缺失会让对应 locale 渲染回退。
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "i18n" / "data"
LOCALES = ("zh_CN", "zh_TW", "en_US")


def _load_keys(locale: str) -> set[str]:
    return set(json.loads((DATA_DIR / f"{locale}.json").read_text()).keys())


def test_three_locales_have_same_key_set():
    """三文件 key 集合完全相等 —— 加 key 必须三文件都加。"""
    zh_cn = _load_keys("zh_CN")
    zh_tw = _load_keys("zh_TW")
    en_us = _load_keys("en_US")

    missing_in_zh_tw = zh_cn - zh_tw
    missing_in_en_us = zh_cn - en_us
    extra_in_zh_tw = zh_tw - zh_cn
    extra_in_en_us = en_us - zh_cn

    assert not missing_in_zh_tw, f"zh_TW 缺 key: {sorted(missing_in_zh_tw)}"
    assert not missing_in_en_us, f"en_US 缺 key: {sorted(missing_in_en_us)}"
    assert not extra_in_zh_tw, f"zh_TW 多 key: {sorted(extra_in_zh_tw)}"
    assert not extra_in_en_us, f"en_US 多 key: {sorted(extra_in_en_us)}"


def test_i18n_extract_directive_keys_match_lang_meta():
    """i18n.extract.directive.* 键集合 == _LANG_META 键集合。"""
    from app.core.i18n.lang_meta import _LANG_META

    all_keys = _load_keys("zh_CN") | _load_keys("zh_TW") | _load_keys("en_US")
    expected = {f"i18n.extract.directive.{lang}" for lang in _LANG_META}
    missing = expected - all_keys
    assert not missing, f"i18n.extract.directive.* 缺: {sorted(missing)}"
