import pytest

from app.core.i18n.messages import Keys, reload_catalogs
from app.core.i18n.startup_check import assert_catalog_complete


def test_passes_with_complete_en_us():
    # The catalog fixtures must already be complete (T01).
    assert_catalog_complete()  # no raise


def test_fails_when_en_us_key_missing(monkeypatch):
    # reload_catalogs() drops lru_cache and re-reads from disk so any prior
    # test that mutated the cached dict cannot leak into this one.
    catalogs = reload_catalogs()
    removed = catalogs["en-US"].pop(Keys.HTTP_TEMPLATE_NOT_FOUND.value, None)
    if removed is None:
        pytest.skip("Test fixture: HTTP_TEMPLATE_NOT_FOUND missing in en-US already")
    try:
        with pytest.raises(RuntimeError, match="en-US"):
            assert_catalog_complete()
    finally:
        catalogs["en-US"][Keys.HTTP_TEMPLATE_NOT_FOUND.value] = removed
        # Restore the on-disk state too so the cache and disk agree.
        reload_catalogs()


@pytest.mark.skip(reason="requires T06 fixtures (zh_cn_client)")
def test_middleware_resolves_accept_language(zh_cn_client):
    """HTTP layer test using FastAPI TestClient. Implemented in T06.
    The middleware contract is verified by passing the locale downstream as
    Content-Language response header."""
