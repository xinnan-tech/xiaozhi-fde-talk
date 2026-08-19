"""Integration tests for WS handler i18n: `_fail` localization + close reasons.

Covers T11 step 1 verbatim from the task brief. These tests run as integration
tests (pytest_collection_modifyitems auto-skips when the server is offline), so
the imports are cheap. Locale is set via the `*_locale` fixtures in
tests/conftest.py, which restore the prior contextvar after each test.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.i18n import Keys
from app.transport.websocket.handler import _fail


@pytest.mark.asyncio
async def test_fail_localizes_message_in_zh_cn(zh_cn_locale):
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    await _fail(ws, code="bad_handshake", close_code=4000)
    args, _ = ws.send.call_args
    payload = json.loads(args[0])
    assert payload["code"] == "bad_handshake"
    assert payload["i18n_key"] == "ws.bad_handshake"
    assert payload["message"] == "握手失败"


@pytest.mark.asyncio
async def test_fail_parametric_key_in_en_us(en_locale):
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    await _fail(
        ws, code="asr_unavailable",
        i18n_key=Keys.WS_ASR_CONNECT_FAIL, reason="connection refused",
    )
    payload = json.loads(ws.send.call_args.args[0])
    assert payload["code"] == "asr_unavailable"
    assert payload["i18n_key"] == Keys.WS_ASR_CONNECT_FAIL.value
    assert payload["message"] == "Voice recognition (ASR) connection failed: connection refused"


@pytest.mark.asyncio
async def test_fail_parametric_key_in_zh_tw(zh_tw_locale):
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    await _fail(
        ws, code="asr_unavailable",
        i18n_key=Keys.WS_ASR_CONNECT_FAIL, reason="connection refused",
    )
    payload = json.loads(ws.send.call_args.args[0])
    assert payload["message"] == "語音識別（ASR）連線失敗：connection refused"


@pytest.mark.asyncio
async def test_close_reason_carries_localized_message(en_locale):
    """`_fail(code="session_ended", close_code=4406)` uses the default
    `_WS_ERROR_KEY["session_ended"]` lookup → `Keys.WS_SESSION_ENDED` → the
    verbose message ("Session ended, please create a new interview"). The
    shorter `ws.close.session_ended` ("Interview ended") is reserved for
    runtime.py eviction (separate code path that doesn't go through _fail)."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    await _fail(ws, code="session_ended", close_code=4406)
    close_kwargs = ws.close.call_args.kwargs
    assert close_kwargs["code"] == 4406
    reason = close_kwargs["reason"]
    if isinstance(reason, bytes):
        reason = reason.decode("utf-8", errors="ignore")
    assert reason == "Session ended, please create a new interview"


@pytest.mark.asyncio
async def test_close_reason_carries_localized_message_zh_cn(zh_cn_locale):
    """close reason bytes must encode the localized message verbatim (not
    the wire code, not English fallback). Verifies the encoder branch in
    `_fail()` that calls `.encode("utf-8")`."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    await _fail(ws, code="session_ended", close_code=4406)
    reason = ws.close.call_args.kwargs["reason"]
    if isinstance(reason, bytes):
        reason = reason.decode("utf-8", errors="ignore")
    assert reason == "会话已结束，请新建访谈继续"


@pytest.mark.asyncio
async def test_runtime_eviction_uses_short_close_reason(zh_cn_locale):
    """runtime.py's `_evict_fn(4406, ...)` path uses the short close-reason
    key `Keys.WS_CLOSE_SESSION_ENDED` (not the verbose WS_SESSION_ENDED).
    Smoke check via direct t() call (the actual eviction is wired in T11 step 4)."""
    from app.core.i18n import t, Keys
    assert t(Keys.WS_CLOSE_SESSION_ENDED.value, locale="en-US") == "Interview ended"
    assert t(Keys.WS_CLOSE_SESSION_ENDED.value, locale="zh-CN") == "访谈已结束"
    assert t(Keys.WS_CLOSE_SESSION_ENDED.value, locale="zh-TW") == "訪談已結束"
