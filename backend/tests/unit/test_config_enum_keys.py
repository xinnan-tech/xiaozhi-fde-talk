"""ENUM_KEYS 校验 + 新默认值。"""
import pytest

from app.core.config_store import DEFAULTS, ENUM_KEYS, validate_value
from app.core.i18n.errors import I18nError
from app.core.i18n.lang_meta import derived_output_language_enum
from app.core.i18n.messages import Keys


def test_enum_keys_dict_has_two_keys():
    assert set(ENUM_KEYS.keys()) == {"asr.language", "llm.output_language"}


def test_enum_keys_values_are_correct_sets():
    assert ENUM_KEYS["asr.language"] == {"zh", "yue", "en"}
    # llm.output_language 从 derived_output_language_enum() 派生（10 条头部语种）——
    # 加语种只改 _LANG_META 一处，断言改成"完全等于派生值"以防漂移。
    assert ENUM_KEYS["llm.output_language"] == derived_output_language_enum()


def test_validate_value_accepts_asr_zh():
    validate_value("asr.language", "zh")  # 不抛


def test_validate_value_accepts_asr_yue():
    validate_value("asr.language", "yue")  # 不抛


def test_validate_value_accepts_asr_en():
    validate_value("asr.language", "en")  # 不抛


def test_validate_value_rejects_asr_fr():
    with pytest.raises(I18nError) as ei:
        validate_value("asr.language", "fr")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["field"] == "asr.language"
    assert ei.value.params["value"] == "fr"
    assert ei.value.http_status == 400


def test_validate_value_accepts_llm_zh_cn():
    validate_value("llm.output_language", "zh_cn")  # 不抛


def test_validate_value_accepts_llm_zh_tw():
    validate_value("llm.output_language", "zh_tw")  # 不抛


def test_validate_value_accepts_llm_en():
    validate_value("llm.output_language", "en")  # 不抛


def test_validate_value_rejects_llm_zh_bare():
    """旧 zh（不带地区）应被拒——避免误选输出到错误语种。"""
    with pytest.raises(I18nError) as ei:
        validate_value("llm.output_language", "zh")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["field"] == "llm.output_language"
    assert ei.value.params["value"] == "zh"
    assert ei.value.http_status == 400


def test_validate_value_keys_independent():
    """asr.language 非法不应该影响 llm.output_language，反之亦然。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.language", "fr")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    # 反向不抛
    validate_value("llm.output_language", "zh_cn")


def test_defaults_include_language_keys():
    assert DEFAULTS["asr.language"] == "zh"
    assert DEFAULTS["llm.output_language"] == "zh_cn"


def test_default_idle_timeout_is_30_minutes():
    """用户原话：「idle_timeout_s改大一点，默认改成30分钟」。"""
    assert DEFAULTS["session.idle_timeout_s"] == "1800.0"


def test_default_llm_base_url_is_dashscope():
    """用户原话：「llm.base_url 默认改成 https://dashscope.aliyuncs.com/compatible-mode/v1」。"""
    assert DEFAULTS["llm.base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
