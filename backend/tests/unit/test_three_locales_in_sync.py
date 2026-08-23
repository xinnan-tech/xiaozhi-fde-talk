"""多语种 i18n 文件 schema 同步守护。

加新 key 必须所有 locale 文件同时加，否则任意一文件缺失会让对应 locale
渲染回退到 key 字面量。Wave 4 之后 directive 文案归 `_EXTRACT_DIRECTIVES`
模块字典，不再走 i18n 文件。
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "core" / "i18n" / "data"
LOCALES = ("zh_CN", "zh_TW", "en_US", "vi_VN")


def _load_keys(locale: str) -> set[str]:
    return set(json.loads((DATA_DIR / f"{locale}.json").read_text()).keys())


def test_all_locales_have_same_key_set():
    """四文件 key 集合完全相等——加 key 必须四文件都加。"""
    loaded = {loc: _load_keys(loc) for loc in LOCALES}
    reference_loc = LOCALES[0]
    reference = loaded[reference_loc]
    for loc in LOCALES[1:]:
        missing = reference - loaded[loc]
        extra = loaded[loc] - reference
        assert not missing, f"{loc} 缺 key: {sorted(missing)}"
        assert not extra, f"{loc} 多 key: {sorted(extra)}"