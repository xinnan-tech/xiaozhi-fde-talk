# tests/unit/test_i18n_catalog.py
import pytest
from app.core.i18n.locales import SUPPORTED, DEFAULT
from app.core.i18n.translator import t
from app.core.i18n.messages import Keys, load_catalogs


LOCALES = sorted(SUPPORTED)


@pytest.mark.parametrize("key", [k for k in Keys])
@pytest.mark.parametrize("locale", LOCALES)
def test_every_key_translates(key, locale):
    """Each Keys.X must resolve in each supported locale. Since T01 commits
    zh_CN.json and zh_TW.json with full coverage of every Keys member, this
    test exercises real translations — NOT the en-US fallback path."""
    msg = t(key.value, locale=locale)
    assert isinstance(msg, str) and msg.strip(), \
        f"empty translation for {key.value} in {locale}"
    # Sanity: en-US and zh-CN must NOT be byte-identical (real translation).
    if locale in {"zh-CN", "zh-TW"}:
        en_msg = t(key.value, locale="en-US")
        assert msg != en_msg, (
            f"{key.value}@{locale} matches en-US — translation missing?"
        )


# NOTE: `Keys ⊆ en-US` and `en-US ⊆ Keys` are both verified by T01's
# `test_every_key_has_en_us_translation` + `test_catalog_keys_are_subset_of_keys_enum`
# + `test_all_locales_have_same_keys`. No need to repeat them here.
