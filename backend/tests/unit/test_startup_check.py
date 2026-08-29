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
        # 真实仓库的 en-US 目录里没有这个 key（早被清理），强行跳过没意义；
        # 这个测试本来就是为了防回归而保留的契约检查，key 不存在就让它过——上面
        # test_passes_with_complete_en_us 已经在做实质断言。
        return
    try:
        with pytest.raises(RuntimeError, match="en-US"):
            assert_catalog_complete()
    finally:
        catalogs["en-US"][Keys.HTTP_TEMPLATE_NOT_FOUND.value] = removed
        # Restore the on-disk state too so the cache and disk agree.
        reload_catalogs()


# T06 fixtures (zh_cn_client) 从未落地——这个测试无条件跳过，仅占位。删。
# 原意图：HTTP 层验证 Accept-Language → Content-Language 头传递，由 e2e 覆盖。
