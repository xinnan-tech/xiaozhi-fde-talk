import pytest
from app.core.i18n.negotiator import (
    parse_accept_language,
    normalize_locale_tag,
    resolve_locale,
)
from app.core.i18n.locales import DEFAULT, SUPPORTED


@pytest.mark.parametrize("header,expected", [
    ("",                  "zh-CN"),
    ("*",                 "zh-CN"),
    ("en-US",             "en-US"),
    ("en",                "en-US"),
    ("en-XX",             "en-US"),
    ("zh-CN",             "zh-CN"),
    ("zh-TW",             "zh-TW"),
    ("zh",                "zh-CN"),
    ("zh-Hans-CN",        "zh-CN"),
    ("zh-SG",             "zh-CN"),
    ("zh-TW,en;q=0.5",    "zh-TW"),
    ("en;q=0.5,zh-TW",    "zh-TW"),
    ("zh-CN;q=0.1",       "zh-CN"),
    ("fr-FR",             "zh-CN"),
    ("fr-FR,zh-CN;q=0.9", "zh-CN"),
])
def test_parse_accept_language(header, expected):
    result = parse_accept_language(header, supported=set(SUPPORTED), default=DEFAULT)
    assert result.locale == expected


def test_normalize_locale_tag_basic():
    assert normalize_locale_tag("zh-CN") == "zh-CN"
    assert normalize_locale_tag("zh_cn") == "zh-CN"
    assert normalize_locale_tag("zh-CN,en-US;q=0.5") is None
    assert normalize_locale_tag("") is None
    assert normalize_locale_tag("zh") == "zh"
    assert normalize_locale_tag("ZH-cn") == "zh-CN"


def test_resolve_locale_picks_first_supported():
    assert resolve_locale(None, "", "fr-FR", "zh-TW") == "zh-TW"
    assert resolve_locale(None, "", "fr-FR") == DEFAULT


def test_q_zero_is_rejected():
    # q=0 means rejected — should not be returned; falls through to default
    result = parse_accept_language("en;q=0,zh-CN", supported=set(SUPPORTED), default=DEFAULT)
    assert result.locale == "zh-CN"
