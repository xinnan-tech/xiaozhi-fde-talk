"""URL_KEYS 校验：funasr_server.ws_url 只接受 ws/wss 协议 + 主机段非空。

回归 issue #134：原 admin 端 PUT /api/v1/admin/config/asr 写 ws_url 时不校验，
`http://x` / `ftp://x` / `javascript:alert(1)` / `not-a-url` / `  wss://x  `
（前缀空格）一律 200 + {ok:true} 原样落库。runtime 端 websockets.InvalidURI
要等到首次 connect 才抛，admin 配置页拿不到错因——写入层挡掉。

整段 reject 含前后空白的值：runtime `_ws_url.strip()` 会静默吞空格，admin
看不到自己手抖输入的空格。
"""
from __future__ import annotations

import pytest

from app.core.config_store import URL_KEYS, validate_value
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def test_url_keys_exact_set():
    """URL_KEYS 必须是这组 key；新增 URL 字段必须同步更新本断言。"""
    assert set(URL_KEYS.keys()) == {"asr.funasr_server.ws_url"}


def test_url_keys_ws_url_allowed_schemes():
    """funasr_server 是 ws/wss；doubao_stream 走 appid 不进表。"""
    assert URL_KEYS["asr.funasr_server.ws_url"] == {"ws", "wss"}


def test_validate_value_accepts_ws_url_ws():
    validate_value("asr.funasr_server.ws_url", "ws://127.0.0.1:10095")  # 不抛


def test_validate_value_accepts_ws_url_wss():
    validate_value("asr.funasr_server.ws_url", "wss://asr.example.com/ws")  # 不抛


def test_validate_value_accepts_ws_url_with_path():
    validate_value("asr.funasr_server.ws_url", "wss://asr.example.com:8443/path")  # 不抛


def test_validate_value_rejects_ws_url_http():
    """http 协议不是 ws/wss，必须拒。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "http://x")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["field"] == "asr.funasr_server.ws_url"
    assert ei.value.params["value"] == "http://x"
    assert ei.value.http_status == 400


def test_validate_value_rejects_ws_url_ftp():
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "ftp://x")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_ws_url_javascript_xss():
    """javascript: scheme 在 ws_url 上没意义，必须拒。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "javascript:alert(1)")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["value"] == "javascript:alert(1)"
    assert ei.value.http_status == 400


def test_validate_value_rejects_ws_url_no_scheme():
    """纯 'not-a-url' 没有 scheme，必须拒。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "not-a-url")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_ws_url_empty_netloc():
    """scheme 是 ws 但主机段为空（'ws://'）必须拒。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "ws://")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_ws_url_leading_trailing_whitespace():
    """前后空格整段拒：runtime _ws_url.strip() 会静默吞空格，admin 看不到自己手抖输入。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "  wss://x  ")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["value"] == "  wss://x  "
    assert ei.value.http_status == 400
