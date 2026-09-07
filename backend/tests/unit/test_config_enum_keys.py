"""ENUM_KEYS 校验 + 新默认值。

ASR 语种按 provider 分键（豆包流式 ea5dbd3 引入）——asr.funasr_server.language
是 FunASR 短码三选（zh/yue/en），asr.doubao_stream.language 是豆包 locale 长码。
共享聚合键「asr.language」没有意义：两个 provider 语种列表互不兼容。
"""
import pytest

from app.core.config_store import DEFAULTS, ENUM_KEYS, validate_value
from app.core.i18n.errors import I18nError
from app.core.i18n.lang_meta import derived_output_language_enum
from app.core.i18n.messages import Keys


def test_enum_keys_exact_set():
    """ENUM_KEYS 必须是这组 key；新增枚举（如未来 ocr.model）必须同步更新本断言。

    asr.type 加入的原因：set_many 过滤非激活 ASR 字段时拼 f"asr.{type}."
    前缀，type 字符串必须在白名单内——靠 ENUM 校验兜住（含空白 / 未知
    provider）以免 filter 静默丢配置后 admin 收到 200「保存成功」（#178 评审）。
    """
    assert set(ENUM_KEYS.keys()) == {
        "asr.funasr_server.language",
        "asr.doubao_stream.language",
        "asr.type",
        "llm.output_language",
        "llm.type",
        "ocr.type",
    }


def test_validate_value_rejects_doubao_api_key_empty():
    """API Key 留空时不能落库，否则首次握手才会失败。
    写入侧必须拦：空白（含全空格）一律 400。
    """
    from app.core.config_store import REQUIRED_STRING_KEYS
    assert "asr.doubao_stream.api_key" in REQUIRED_STRING_KEYS

    for bad in ("", " ", "\t", "\n", "   \t\n"):
        with pytest.raises(I18nError) as ei:
            validate_value("asr.doubao_stream.api_key", bad)
        assert ei.value.code == Keys.CONFIG_INVALID_REQUIRED_STRING.value
        assert ei.value.params["name"] == "asr.doubao_stream.api_key"
        assert ei.value.http_status == 400


def test_validate_value_accepts_doubao_required_strings_non_empty():
    """API Key 非空时放行。"""
    validate_value("asr.doubao_stream.api_key", "ak-1234567890")


def test_enum_keys_values_are_correct_sets():
    assert ENUM_KEYS["asr.funasr_server.language"] == {"zh", "yue", "en"}
    # 豆包完整 locale 列表（含 yue-CN 粤语）；新增条目同步在 doubao_stream 适配器。
    assert ENUM_KEYS["asr.doubao_stream.language"] == {
        "zh-CN", "en-US", "ja-JP", "id-ID", "es-MX", "pt-BR", "de-DE",
        "fr-FR", "ko-KR", "fil-PH", "ms-MY", "th-TH", "ar-SA", "it-IT",
        "bn-BD", "el-GR", "nl-NL", "ru-RU", "tr-TR", "vi-VN", "pl-PL",
        "ro-RO", "ne-NP", "uk-UA", "yue-CN",
    }
    # llm.output_language 从 derived_output_language_enum() 派生（10 条头部语种）——
    # 加语种只改 _LANG_META 一处，断言改成"完全等于派生值"以防漂移。
    assert ENUM_KEYS["llm.output_language"] == derived_output_language_enum()
    # llm.type 跟 factory.py:_REGISTRY 同步——{openai, stub}；漏写会让脏值落库
    # 后续 create_llm() 抛 ValueError 时全站 LLM 调 500。
    assert ENUM_KEYS["llm.type"] == {"openai", "stub"}
    # ocr.type 跟 factory.py supported_providers 同步——{openai, baidu}
    assert ENUM_KEYS["ocr.type"] == {"openai", "baidu"}
    # asr.type 跟 asr.* 子 key 命名一致（funasr_server / doubao_stream）——
    # 加新 provider 需同时扩这里 + ALL_B_KEYS + DEFAULTS。
    assert ENUM_KEYS["asr.type"] == {"funasr_server", "doubao_stream"}


def test_validate_value_accepts_funasr_zh():
    validate_value("asr.funasr_server.language", "zh")  # 不抛


def test_validate_value_accepts_funasr_yue():
    validate_value("asr.funasr_server.language", "yue")  # 不抛


def test_validate_value_accepts_funasr_en():
    validate_value("asr.funasr_server.language", "en")  # 不抛


def test_validate_value_rejects_funasr_fr():
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.language", "fr")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["field"] == "asr.funasr_server.language"
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


def test_validate_value_accepts_llm_type_openai():
    validate_value("llm.type", "openai")  # 不抛


def test_validate_value_accepts_llm_type_stub():
    validate_value("llm.type", "stub")  # 不抛


def test_validate_value_rejects_llm_type_garbage():
    """任意未识别 provider（含 anthropic / google / 完全乱写 / 空串）必须拒。

    写入层校验是为了在落库之前挡住脏值——一旦落库，首次按 type 构造
    provider 时 factory 抛 ValueError，admin PUT 链路没 catch，全站 500。
    """
    for bad in ("anthropic", "google", "totally_fake", ""):
        with pytest.raises(I18nError) as ei:
            validate_value("llm.type", bad)
        assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
        assert ei.value.params["field"] == "llm.type"
        assert ei.value.params["value"] == bad
        assert ei.value.http_status == 400


def test_validate_value_keys_independent():
    """asr.* 非法不应该影响 llm.output_language，反之亦然。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.language", "fr")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    # 反向不抛
    validate_value("llm.output_language", "zh_cn")


def test_defaults_include_language_keys():
    assert DEFAULTS["asr.funasr_server.language"] == "zh"
    assert DEFAULTS["asr.doubao_stream.language"] == "zh-CN"
    assert DEFAULTS["llm.output_language"] == "zh_cn"


def test_default_idle_timeout_is_30_minutes():
    """用户原话：「idle_timeout_s改大一点，默认改成30分钟」。"""
    assert DEFAULTS["session.idle_timeout_s"] == "1800.0"


def test_default_llm_base_url_is_dashscope():
    """用户原话：「llm.base_url 默认改成 https://dashscope.aliyuncs.com/compatible-mode/v1」。"""
    assert DEFAULTS["llm.base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_validate_value_rejects_unhashable_enum_inputs():
    """issue #209：asr.type 传 list / dict 撞 unhashable → 500 改为 400 + i18n。

    旧实现 `value not in allowed`（set[str]）对 unhashable 类型直接抛 TypeError，
    未捕获冒到 FastAPI 默认 handler 转 500；admin 看到 Internal Server Error 没法
    定位。加 isinstance(value, str) 兜底，统一走 400 + invalid_enum_value。
    """
    for bad in (["funasr_server"], {"a": "b"}, [], {}):
        with pytest.raises(I18nError) as ei:
            validate_value("asr.type", bad)
        assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
        assert ei.value.params["field"] == "asr.type"
        assert ei.value.params["value"] == bad
        assert ei.value.http_status == 400
        assert ei.value.params["allowed"] == "doubao_stream / funasr_server"

    # 同样保护对所有 ENUM key 都生效（不只是 asr.type）
    with pytest.raises(I18nError) as ei:
        validate_value("llm.type", ["openai"])
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400
