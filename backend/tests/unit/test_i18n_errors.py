"""I18nError + named subclasses + WsError key map.

Locks the user-facing contract for T04: every error has a stable code, an
http_status, structured params, and a localized() string resolved via the
existing t() translator. Legacy aliases (ConcurrentLimitError / IllegalTransitionError)
remain importable and are the SAME class as their named subclass (so existing
`except` blocks keep working).
"""
import pytest
from app.core.i18n.errors import (
    I18nError,
    SessionConcurrentLimitError,
    SessionIllegalTransitionError,
    SessionEditForbiddenError,
    SessionDeleteForbiddenError,
)
from app.core.i18n.messages import Keys
from app.core.i18n import t, force_locale, reset_locale
from app.core.exceptions import (
    ConcurrentLimitError,
    IllegalTransitionError,
    AuthError,
)
from app.core.constants import _WS_ERROR_KEY, WsError


def test_i18n_error_carries_code_and_params():
    e = I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
    assert e.code == "http.template.not_found"
    assert e.http_status == 404
    assert e.params == {}


def test_i18n_error_localized_zh_cn_default():
    e = SessionConcurrentLimitError(limit=5)
    assert e.localized(locale="zh-CN") == "活跃访谈数已达上限（5）"


def test_i18n_error_localized_en_us():
    e = SessionConcurrentLimitError(limit=42)
    assert e.localized(locale="en-US") == "Active interview limit reached (42)"


def test_named_subclasses_have_correct_http_status():
    assert SessionConcurrentLimitError(limit=1).http_status == 409
    assert SessionIllegalTransitionError(from_state="ended", to_state="in_progress").http_status == 409
    assert SessionEditForbiddenError(state="active").http_status == 409
    assert SessionDeleteForbiddenError(state="active").http_status == 409


def test_legacy_aliases_still_importable_and_catch_i18n_error():
    # AuthError stays as DomainError (English path) - unaffected.
    with pytest.raises(AuthError):
        raise AuthError("missing token")

    # ConcurrentLimitError must be SAME class as SessionConcurrentLimitError
    # so `except ConcurrentLimitError` continues to work after adoption.
    assert ConcurrentLimitError is SessionConcurrentLimitError
    with pytest.raises(ConcurrentLimitError):
        raise SessionConcurrentLimitError(limit=1)

    # IllegalTransitionError alias works the same way.
    assert IllegalTransitionError is SessionIllegalTransitionError
    with pytest.raises(IllegalTransitionError):
        raise SessionIllegalTransitionError(from_state="a", to_state="b")


def test_ws_error_key_dict_covers_all_enum_values():
    """Every WsError wire code must map to a known i18n key."""
    missing = [m.value for m in WsError if m.value not in _WS_ERROR_KEY]
    assert missing == [], f"WS error codes missing i18n keys: {missing}"
    # And each maps to a real translation (at least en-US).
    from app.core.i18n.messages import load_catalogs
    en = load_catalogs()["en-US"]
    for code, key in _WS_ERROR_KEY.items():
        assert key in en, f"{code} → {key} has no en-US catalog entry"


def test_str_i18n_error_includes_code_for_logging():
    e = SessionConcurrentLimitError(limit=7)
    s = str(e)
    assert "session.concurrent_limit" in s
    # str(e) is for human log readers; structured assertions go through .code / .params.
    assert e.code == "session.concurrent_limit"
    assert e.params["limit"] == 7
