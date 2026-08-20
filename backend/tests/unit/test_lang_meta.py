"""_LANG_META 单一真源派生约束回归。

Stage 1 重构后所有 LLM 输出语种相关 dict 派生自 _LANG_META——任一漂移立刻 fail。
"""
from app.core.i18n import lang_meta
from app.core.i18n.lang_meta import (
    _LANG_META,
    LangMeta,
    derived_fallback_phrases,
    derived_output_language_enum,
    get_lang_meta,
)
from app.core.config_store import ENUM_KEYS


def test_lang_meta_has_head_ten_languages():
    """头部 10 语种手写——加语种改这里。"""
    assert set(_LANG_META.keys()) == {
        "zh_cn", "zh_tw", "en",
        "vi", "ru", "ko", "ja", "fr", "de", "es",
    }


def test_lang_meta_required_fields_non_empty():
    """所有 LangMeta 字段非空——prompt / locale 协商会用到。"""
    for code, meta in _LANG_META.items():
        assert meta.native_name.strip(), f"{code} native_name 空"
        assert meta.english_name.strip(), f"{code} english_name 空"
        assert meta.bcp47.strip(), f"{code} bcp47 空"
        assert meta.fallback_lang.strip(), f"{code} fallback_lang 空"
        # bcp47 必须是大写区域标签
        assert "-" in meta.bcp47, f"{code} bcp47 缺 region: {meta.bcp47!r}"


def test_get_lang_meta_known():
    """已知语种直接返回对应 LangMeta。"""
    vi = get_lang_meta("vi")
    assert vi.native_name == "Tiếng Việt"
    assert vi.english_name == "Vietnamese"
    assert vi.bcp47 == "vi-VN"


def test_get_lang_meta_case_insensitive():
    """大小写不规整——返回归一后 LangMeta。"""
    assert get_lang_meta("VI").native_name == get_lang_meta("vi").native_name
    assert get_lang_meta("ZH_CN").native_name == "简体中文"


def test_get_lang_meta_empty_or_none_falls_back_to_zh_cn():
    """None / 空串 → zh_cn 默认值（与生产 `(lang or "zh_cn").lower() or "zh_cn"`
    模式一致，保持向后兼容）。"""
    zh = get_lang_meta(None)
    assert zh.bcp47 == "zh-CN"
    assert get_lang_meta("").bcp47 == "zh-CN"


def test_get_lang_meta_unknown_falls_back_to_en():
    """长尾语种（ar / pt / sw 等）不在 _LANG_META → 走 en——pivot fallback_lang 兜底。"""
    ar = get_lang_meta("ar")
    assert ar.bcp47 == "en-US"
    pt = get_lang_meta("pt-BR")
    assert pt.bcp47 == "en-US"


def test_fallback_lang_always_known():
    """fallback_lang 必须是 _LANG_META 已注册的语种——pivot 调用时不能 KeyError。"""
    for code, meta in _LANG_META.items():
        assert meta.fallback_lang in _LANG_META, (
            f"{code}.fallback_lang={meta.fallback_lang!r} 不在 _LANG_META"
        )


def test_derived_fallback_phrases_keys_match_lang_meta():
    """兜底短语键集合 == _LANG_META 键集合——派生约束。"""
    phrases = derived_fallback_phrases()
    assert set(phrases.keys()) == set(_LANG_META.keys())


def test_derived_fallback_phrases_non_empty():
    """每条短语非空——后处理 _fill_dangling_labels 拿到空串会注入空 label。"""
    for code, phrase in derived_fallback_phrases().items():
        assert phrase.strip(), f"{code} 兜底短语为空"


def test_derived_fallback_phrases_zh_values_preserved():
    """zh_cn / zh_tw / en 三条短语值与重构前完全相同——保持现有报告兼容性。"""
    phrases = derived_fallback_phrases()
    assert phrases["zh_cn"] == "本次访谈未提及"
    assert phrases["zh_tw"] == "本次訪談未提及"
    assert phrases["en"] == "Not mentioned in this interview."


def test_derived_fallback_phrases_returns_fresh_dict():
    """返回的是 dict 副本——调用方修改不污染模块级常量。"""
    phrases = derived_fallback_phrases()
    phrases["zh_cn"] = "tampered"
    assert derived_fallback_phrases()["zh_cn"] == "本次访谈未提及"


def test_derived_output_language_enum_matches_lang_meta():
    """ENUM_KEYS["llm.output_language"] 必须从 _LANG_META 派生——派生约束。"""
    enum = derived_output_language_enum()
    assert enum == set(_LANG_META.keys())


def test_config_store_enum_uses_derived_value():
    """config_store 已用派生值——不是硬编码。"""
    assert ENUM_KEYS["llm.output_language"] == set(_LANG_META.keys())


def test_reports_fallback_uses_derived_value():
    """reports._FALLBACK_BY_LANG 已用派生值。"""
    from app.services.reports.generator import _FALLBACK_BY_LANG
    assert _FALLBACK_BY_LANG == derived_fallback_phrases()