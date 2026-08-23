"""Regression test for `_extract_llm_error` / `_extract_asr_error` dispatch.

The adapter layer raises `LLMError = I18nError` (and `ASRProviderError` is also
`I18nError`). Earlier versions of these helpers matched on `LLMProviderError`
(which is a different class with zero raise sites) and on substring keywords
inside `str(exc)` — both dead paths, leaving every LLM failure misclassified
as `DIAG_LLM_INVOKE_FAIL_TYPED` ("server" / "调LLM失败").

These tests pin the new dispatch: each `exc.code` value routes to the
correct diagnostic classification (config_missing / auth / quota /
unreachable / server).
"""
from __future__ import annotations

import pytest

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.services.diagnostics import _extract_asr_error, _extract_llm_error


# ---------- LLM ----------

def test_llm_not_configured_routes_to_config_missing():
    exc = I18nError(Keys.LLM_NOT_CONFIGURED.value, http_status=502,
                    base_url="", api_key="", model="")
    r = _extract_llm_error(exc)
    assert r["code"] == "config_missing"
    assert r["i18n_key"] == Keys.DIAG_LLM_CONFIG_MISSING_RAW.value


def test_llm_timeout_routes_to_unreachable():
    exc = I18nError(Keys.LLM_TIMEOUT.value, http_status=504, budget=15)
    r = _extract_llm_error(exc)
    assert r["code"] == "unreachable"
    assert r["i18n_key"] == Keys.DIAG_LLM_UNREACHABLE_TYPED.value


def test_llm_non_retryable_401_routes_to_auth():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=401, body="invalid api key")
    r = _extract_llm_error(exc)
    assert r["code"] == "auth"
    assert r["i18n_key"] == Keys.DIAG_LLM_AUTH_FAIL.value


def test_llm_non_retryable_403_routes_to_auth():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=403, body="forbidden")
    r = _extract_llm_error(exc)
    assert r["code"] == "auth"


def test_llm_non_retryable_429_routes_to_quota():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=429, body="rate limit")
    r = _extract_llm_error(exc)
    assert r["code"] == "quota"
    assert r["i18n_key"] == Keys.DIAG_LLM_RATE_LIMIT.value


def test_llm_non_retryable_400_routes_to_config_missing():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=400, body="bad model name")
    r = _extract_llm_error(exc)
    assert r["code"] == "config_missing"
    assert r["i18n_key"] == Keys.DIAG_LLM_BAD_CONFIG.value


def test_llm_non_retryable_404_routes_to_config_missing():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=404, body="model not found")
    r = _extract_llm_error(exc)
    assert r["code"] == "config_missing"


def test_llm_non_retryable_500_routes_to_server():
    exc = I18nError(Keys.LLM_NON_RETRYABLE.value, http_status=502,
                    status=500, body="boom")
    r = _extract_llm_error(exc)
    assert r["code"] == "server"
    assert r["i18n_key"] == Keys.DIAG_LLM_SERVICE_FAIL.value


def test_llm_retry_exhausted_routes_to_server():
    exc = I18nError(Keys.LLM_RETRY_EXHAUSTED.value, http_status=502,
                    retries=3, last_err="HTTP 502")
    r = _extract_llm_error(exc)
    assert r["code"] == "server"
    assert r["i18n_key"] == Keys.DIAG_LLM_INVOKE_FAIL.value


def test_llm_invalid_json_routes_to_server():
    exc = I18nError(Keys.LLM_INVALID_JSON.value, http_status=502)
    r = _extract_llm_error(exc)
    assert r["code"] == "server"
    assert r["i18n_key"] == Keys.DIAG_LLM_INVOKE_FAIL.value


def test_llm_no_json_block_routes_to_server():
    exc = I18nError(Keys.LLM_NO_JSON_BLOCK.value, http_status=502)
    r = _extract_llm_error(exc)
    assert r["code"] == "server"


def test_llm_schema_mismatch_routes_to_server():
    exc = I18nError(Keys.LLM_SCHEMA_MISMATCH.value, http_status=502)
    r = _extract_llm_error(exc)
    assert r["code"] == "server"


# ---------- ASR ----------

def test_asr_connect_fail_unreachable_reason_routes_to_unreachable():
    exc = I18nError(Keys.ASR_CONNECT_FAIL.value, http_status=502,
                    ws_url="wss://x", reason="Connection refused")
    r = _extract_asr_error(exc)
    assert r["code"] == "unreachable"
    assert r["i18n_key"] == Keys.DIAG_ASR_UNREACHABLE.value


def test_asr_connect_fail_tls_reason_routes_to_config_missing():
    exc = I18nError(Keys.ASR_CONNECT_FAIL.value, http_status=502,
                    ws_url="wss://x", reason="TLS handshake failed")
    r = _extract_asr_error(exc)
    assert r["code"] == "config_missing"
    assert r["i18n_key"] == Keys.DIAG_ASR_BAD_URL.value


def test_asr_dead_routes_to_server():
    exc = I18nError(Keys.ASR_DEAD.value, http_status=502)
    r = _extract_asr_error(exc)
    assert r["code"] == "server"
    assert r["i18n_key"] == Keys.DIAG_ASR_DEAD.value


def test_asr_feed_fail_routes_to_server():
    exc = I18nError(Keys.ASR_FEED_FAIL.value, http_status=502, err="send timeout")
    r = _extract_asr_error(exc)
    assert r["code"] == "server"
    assert r["i18n_key"] == Keys.DIAG_ASR_INVOKE_FAIL_TYPED.value


# ---------- regression: user-facing message must not leak I18nError debug repr ----------
#
# I18nError.__str__ 故意返回 "i18n:<code>{<params>}" 给日志看，
# 之前 _extract_llm_error / _extract_asr_error 直接拿 str(exc) 拼进模板，
# 会把内部字段名（last_err / snippet / retries 等）一起泄漏给前端。
# 这些测试断言 message 字段对前端用户干净。

def test_llm_retry_exhausted_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.LLM_RETRY_EXHAUSTED.value, http_status=502,
                    retries=1, last_err="ConnectError: All connection attempts failed")
    r = _extract_llm_error(exc)
    assert r["code"] == "server"
    msg = r["message"]
    # 不应泄漏 I18nError 的调试串
    assert "i18n:" not in msg
    assert "{" not in msg or "{" not in msg.split("LLM 调用失败：", 1)[-1]
    # 真实底层错误必须透出给前端
    assert "ConnectError: All connection attempts failed" in msg


def test_llm_not_configured_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.LLM_NOT_CONFIGURED.value, http_status=502,
                    base_url="", api_key="", model="")
    r = _extract_llm_error(exc)
    assert r["code"] == "config_missing"
    assert "i18n:" not in r["message"]


def test_llm_timeout_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.LLM_TIMEOUT.value, http_status=504, budget=15)
    r = _extract_llm_error(exc)
    assert r["code"] == "unreachable"
    assert "i18n:" not in r["message"]


def test_llm_no_json_block_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.LLM_NO_JSON_BLOCK.value, http_status=502,
                    snippet="model said lol")
    r = _extract_llm_error(exc)
    assert r["code"] == "server"
    assert "i18n:" not in r["message"]
    # snippet 应该透出
    assert "model said lol" in r["message"]


def test_asr_dead_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.ASR_DEAD.value, http_status=502)
    r = _extract_asr_error(exc)
    assert r["code"] == "server"
    assert "i18n:" not in r["message"]


def test_asr_feed_fail_message_does_not_leak_debug_repr():
    exc = I18nError(Keys.ASR_FEED_FAIL.value, http_status=502, err="send timeout")
    r = _extract_asr_error(exc)
    assert r["code"] == "server"
    assert "i18n:" not in r["message"]
    assert "send timeout" in r["message"]