from __future__ import annotations

import logging
from typing import Any

from .context import current_locale
from .locales import DEFAULT, SUPPORTED
from .messages import load_catalogs

_log = logging.getLogger(__name__)


def _resolve_locale(loc: str | None) -> str:
    if loc is None:
        loc = current_locale()
    if loc not in SUPPORTED:
        loc = DEFAULT
    return loc


def t(key: str, *, locale: str | None = None, **params: Any) -> str:
    """Resolve a message key. Resolution order:
        (locale arg | current_locale()) → en-US → KeyError.

    Format spec: `msg.format(**params)` is invoked verbatim. Missing or
    mistyped params raise KeyError; mismatched format specs across locales
    (e.g. `{x!r}` in en-US, plain `{x}` in zh-CN) raise at call time.
    See T01 catalog NOTE for cross-locale format-string consistency rules.
    """
    target = _resolve_locale(locale)
    catalogs = load_catalogs()
    msg = catalogs.get(target, {}).get(key)
    if msg is None and target != "en-US":
        _log.debug("i18n.fallback_used locale=%s key=%s", target, key)
        msg = catalogs["en-US"].get(key)
    if msg is None:
        raise KeyError(key)
    return msg.format(**params) if params else msg
