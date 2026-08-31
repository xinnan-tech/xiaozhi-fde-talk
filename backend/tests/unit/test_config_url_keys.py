"""覆盖 ws_url / llm.base_url / ocr.base_url 写入校验：scheme 必须在白名单、
非空 netloc、拒整段前后空白；空串放行（让 admin 清空 ws_url 走 fail-fast）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config_store import URL_KEYS, ConfigStore, validate_value
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def test_url_keys_exact_set():
    """URL_KEYS 必须是这组 key；新增 URL 字段必须同步更新本断言。"""
    assert set(URL_KEYS.keys()) == {
        "asr.funasr_server.ws_url",
        "llm.base_url",
        "ocr.base_url",
    }


def test_url_keys_ws_url_allowed_schemes():
    """funasr_server 是 ws/wss；doubao_stream 走 appid 不进表。"""
    assert URL_KEYS["asr.funasr_server.ws_url"] == {"ws", "wss"}


def test_url_keys_http_base_urls_allowed_schemes():
    """LLM / OCR 入口走 HTTP(S)。"""
    assert URL_KEYS["llm.base_url"] == {"http", "https"}
    assert URL_KEYS["ocr.base_url"] == {"http", "https"}


def test_validate_value_accepts_ws_url_ws():
    validate_value("asr.funasr_server.ws_url", "ws://127.0.0.1:10095")  # 不抛


def test_validate_value_accepts_ws_url_wss():
    validate_value("asr.funasr_server.ws_url", "wss://asr.example.com/ws")  # 不抛


def test_validate_value_accepts_ws_url_with_path():
    validate_value("asr.funasr_server.ws_url", "wss://asr.example.com:8443/path")  # 不抛


def test_validate_value_accepts_url_keys_empty_string():
    """空串放行：admin PUT "" 清空 ws_url → runtime 走 funasr_server.py:144
    未配置即 fail-fast 路径。llm.base_url / ocr.base_url 同理。"""
    validate_value("asr.funasr_server.ws_url", "")  # 不抛
    validate_value("llm.base_url", "")  # 不抛
    validate_value("ocr.base_url", "")  # 不抛


def test_validate_value_accepts_llm_base_url_https():
    validate_value("llm.base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")  # 不抛


def test_validate_value_accepts_ocr_base_url_http():
    validate_value("ocr.base_url", "http://aip.baidubce.com")  # 不抛


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


def test_validate_value_rejects_ws_url_javascript_scheme():
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
    """前后空格整段拒：runtime 传给 websockets.connect 的是
    funasr_server.py:150 self._ws_url.rstrip("/")，不去前后空白，会带空格
    抛 InvalidURI，admin 在写入时拿不到结构化错因。"""
    with pytest.raises(I18nError) as ei:
        validate_value("asr.funasr_server.ws_url", "  wss://x  ")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["value"] == "  wss://x  "
    assert ei.value.http_status == 400


def test_validate_value_rejects_llm_base_url_ws():
    """ws 协议不是 http/https，拒。"""
    with pytest.raises(I18nError) as ei:
        validate_value("llm.base_url", "ws://x")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.params["field"] == "llm.base_url"
    assert ei.value.http_status == 400


def test_validate_value_rejects_llm_base_url_whitespace():
    with pytest.raises(I18nError) as ei:
        validate_value("llm.base_url", "  https://x  ")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_ocr_base_url_whitespace():
    with pytest.raises(I18nError) as ei:
        validate_value("ocr.base_url", "  https://x  ")
    assert ei.value.code == Keys.CONFIG_INVALID_ENUM_VALUE.value
    assert ei.value.http_status == 400


async def test_warm_rejects_bad_default_url(monkeypatch):
    """回归 item 1：种入 DEFAULTS 前必须 validate_value，避免 DEFAULTS 写错
    （含非法 scheme / 空 netloc / 全空白）静默落库——首次启动通道与 admin
    PUT 通道同等对待。"""
    from app.core import config_store as cs

    bad_value = "not-a-url"
    monkeypatch.setitem(cs.DEFAULTS, "asr.funasr_server.ws_url", bad_value)
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(cs, "SessionLocal", lambda: session)

    ConfigStore._instance = None
    store = ConfigStore()
    with pytest.raises(I18nError) as ei:
        await store.warm()
    assert ei.value.params["field"] == "asr.funasr_server.ws_url"
    assert ei.value.params["value"] == bad_value
    # 校验失败必须先于 commit：坏值不允许落到 DB（事务未提交 = 在
    # AsyncSession 上下文退出时被丢弃，AsyncMock 不模拟事务回滚，但仍
    # 验证没有 commit 调用）。
    session.commit.assert_not_called()
