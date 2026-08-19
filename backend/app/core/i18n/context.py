from __future__ import annotations

from contextvars import ContextVar, Token

from .locales import DEFAULT

_locale: ContextVar[str] = ContextVar("i18n_locale", default=DEFAULT)


def current_locale() -> str:
    """Locale for the current asyncio task (falls back to DEFAULT in a fresh task).

    In an HTTP request, I18nHTTPMiddleware sets this before dispatching the route
    handler; in a WS connection, the handler `_fail()` sets it from `state.locale`
    at hello time. Both run inside distinct asyncio tasks, so the contextvar is
    naturally per-connection/per-request and does NOT leak across them.
    """
    return _locale.get()


def force_locale(loc: str) -> Token:
    """Override the locale for the current task. Returns a token that must be
    passed to `reset_locale()` in a `try/finally` block.

    WARNING: Do NOT call `force_locale()` mid-request and then `await` something
    that schedules a different request handler without first resetting — the
    ContextVar is per-task, so as long as the await chain stays inside the same
    task, the value persists; but crossing a new task boundary (e.g. spawning a
    background task with `asyncio.create_task` while holding a non-default
    locale) leaks the override into the new task.

    The WS handler intentionally calls this once at hello time and never resets,
    relying on per-task natural isolation.
    """
    if not loc:
        return _locale.set(DEFAULT)
    return _locale.set(loc)


def reset_locale(token: Token) -> None:
    _locale.reset(token)
