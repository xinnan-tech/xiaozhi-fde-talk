import pytest
from app.core.i18n.context import force_locale, reset_locale, current_locale
from app.core.i18n.translator import t
from app.core.i18n.locales import DEFAULT


def test_default_locale_is_zh_cn():
    assert current_locale() == DEFAULT
    # ws.bad_handshake has a translation in every locale by spec contract.
    # Force locale explicitly to avoid relying on the default.
    msg_zh = t("ws.bad_handshake", locale="zh-CN")
    msg_en = t("ws.bad_handshake", locale="en-US")
    assert msg_zh and isinstance(msg_zh, str)
    assert msg_en and isinstance(msg_en, str)
    assert msg_zh != msg_en


def test_force_locale_changes_resolution():
    tok = force_locale("en-US")
    try:
        msg = t("ws.bad_handshake")
        assert msg == "Bad handshake"
    finally:
        reset_locale(tok)


def test_reset_locale_restores_previous():
    tok = force_locale("en-US")
    reset_locale(tok)
    assert current_locale() == DEFAULT


def test_t_falls_back_to_en_us_for_missing_translation(monkeypatch):
    """When a key is missing from the target locale, t() falls back to en-US.

    Implementation note: do NOT mutate-and-cache_clear here. lru_cache rebuilds
    the dict from disk on next call, so a cached mutation is lost and the
    fallback path is never exercised. monkeypatch `load_catalogs` on the
    `translator` module (the bound name `t()` actually calls) with a one-shot
    dict that has the key missing from zh-TW.
    """
    from app.core.i18n import messages, translator

    snapshot = messages.load_catalogs()  # returns cached dict (shared ref)
    modified = {loc: dict(entries) for loc, entries in snapshot.items()}
    modified["zh-TW"].pop("http.template.not_found", None)
    monkeypatch.setattr(translator, "load_catalogs", lambda: modified)

    tok = force_locale("zh-TW")
    try:
        msg = t("http.template.not_found")
        assert msg == "Template not found"
    finally:
        reset_locale(tok)


def test_t_raises_keyerror_for_unknown_key():
    with pytest.raises(KeyError):
        t("definitely.does.not.exist")


def test_t_substitutes_placeholders():
    msg = t("session.concurrent_limit", limit=42)
    assert "42" in msg
