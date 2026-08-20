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
    """i18n.extract.directive.* 键集合 == _LANG_META 键集合（扫三 JSON 文件不调函数）。"""
    from app.core.i18n.lang_meta import _LANG_META

    all_keys = _load_keys("zh_CN") | _load_keys("zh_TW") | _load_keys("en_US")
    expected = {f"i18n.extract.directive.{lang}" for lang in _LANG_META}
    missing = expected - all_keys
    assert not missing, f"i18n.extract.directive.* 缺: {sorted(missing)}"


def test_three_locales_directive_values_identical():
    """i18n.extract.directive.{lang} 三文件 value 必须完全一致——文案归一约定。

    set 同步测试验「key 集合」，但 value 漂移 set 同步测过不了。
    directive 文案是英文模板，三文件一字不差才能在切换 locale 时行为一致。
    """
    from app.core.i18n.lang_meta import _LANG_META

    zh_cn = json.loads((DATA_DIR / "zh_CN.json").read_text())
    zh_tw = json.loads((DATA_DIR / "zh_TW.json").read_text())
    en_us = json.loads((DATA_DIR / "en_US.json").read_text())

    for lang in _LANG_META:
        key = f"i18n.extract.directive.{lang}"
        v_zh_cn = zh_cn.get(key, "")
        v_zh_tw = zh_tw.get(key, "")
        v_en_us = en_us.get(key, "")
        assert v_zh_cn == v_zh_tw, f"{key}: zh_CN({v_zh_cn!r}) != zh_TW({v_zh_tw!r})"
        assert v_zh_cn == v_en_us, f"{key}: zh_CN({v_zh_cn!r}) != en_US({v_en_us!r})"
