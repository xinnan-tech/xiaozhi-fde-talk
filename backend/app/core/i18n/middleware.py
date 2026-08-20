from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .context import force_locale, reset_locale
from .locales import DEFAULT, SUPPORTED
from .negotiator import parse_accept_language


class I18nHTTPMiddleware(BaseHTTPMiddleware):
    """Per-request locale resolution. Priority: X-Lang → Accept-Language → DEFAULT.

    Stores the resolved locale in a ContextVar for `t()` to read inside the request
    handler. Sets `Content-Language` response header so callers can confirm which
    locale was negotiated.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        accept = request.headers.get("accept-language")
        x_lang = request.headers.get("x-lang")

        if x_lang and x_lang in SUPPORTED:
            locale = x_lang
        else:
            neg = parse_accept_language(
                accept,
                supported=set(SUPPORTED),
                default=DEFAULT,
            )
            locale = neg.locale

        token = force_locale(locale)
        try:
            response = await call_next(request)
            response.headers["Content-Language"] = locale
            return response
        finally:
            reset_locale(token)
