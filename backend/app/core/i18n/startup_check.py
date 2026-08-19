from __future__ import annotations

from .messages import Keys, load_catalogs


def assert_catalog_complete() -> None:
    en_us = load_catalogs().get("en-US", {})
    missing = [k.value for k in Keys if k.value not in en_us]
    if missing:
        raise RuntimeError(
            f"i18n en-US catalog incomplete: missing {len(missing)} keys: {missing[:5]}..."
        )
