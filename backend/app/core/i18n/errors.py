"""User-facing exceptions localized at the transport boundary.

`I18nError` carries a stable message code (Keys.X) and arbitrary interpolation
params. Bubbles through to:
  - HTTP: FastAPI exception handler → JSONResponse with localized `detail`
    + stable `code`.
  - WS:   handler `_fail()` resolves message via state.locale → frame
    `message` field.

`str(e)` is intentionally an internal debug string (`i18n:<code>{<params>}`).
Log readers get the structured fields via `e.code` / `e.params`. User-facing
text comes from `e.localized(locale)`.
"""
from __future__ import annotations

from typing import Any, Mapping

from .messages import Keys
from .translator import t


class I18nError(Exception):
    """User-facing error that is translated at the transport boundary."""

    code: str
    http_status: int
    params: Mapping[str, Any]

    def __init__(self, code: str, *, http_status: int = 400, **params: Any) -> None:
        self.code = code
        self.http_status = http_status
        self.params = dict(params)
        # Single-string super().__init__ keeps str(e) informative for logging
        # without exposing the raw params dict via Exception's tuple-repr.
        # Tests assert on ei.value.code / ei.value.params directly, never on str(e).
        super().__init__(f"i18n:{code}{self.params}")

    def localized(self, locale: str | None = None) -> str:
        return t(self.code, locale=locale, **self.params)


class SessionConcurrentLimitError(I18nError):
    def __init__(self, *, limit: int):
        super().__init__(Keys.SESSION_CONCURRENT_LIMIT, http_status=409, limit=limit)


class SessionIllegalTransitionError(I18nError):
    def __init__(self, *, from_state: str, to_state: str):
        super().__init__(
            Keys.SESSION_ILLEGAL_TRANSITION, http_status=409,
            from_state=from_state, to_state=to_state,
        )


class SessionEditForbiddenError(I18nError):
    def __init__(self, *, state: str):
        super().__init__(Keys.SESSION_EDIT_FORBIDDEN, http_status=409, state=state)


class SessionDeleteForbiddenError(I18nError):
    def __init__(self, *, state: str):
        super().__init__(Keys.SESSION_DELETE_FORBIDDEN, http_status=409, state=state)


# ---- Adapter aliases (existing call-sites use these names; preserve import compat) ----
# These get rebound to I18nError at the end of this task after adoption rewrites; until
# then, classes are declared in their original modules.
