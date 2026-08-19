"""领域异常：跨层复用的业务错误类型。

transport 层可统一异常处理（exception_handlers.py）而不依赖具体业务模块。
"""
from __future__ import annotations

# Aliases preserved for backward import. The named I18nError subclasses live in
# app.core.i18n.errors. Code under adoption raises SessionConcurrentLimitError / etc.;
# legacy `except ConcurrentLimitError` and `except IllegalTransitionError` blocks
# in transports/services continue to match because these names are the SAME class.
# ASRProviderError is also an I18nError alias so `except ASRProviderError` in
# services/diagnostics.py catches exceptions raised by funasr_server.py.
from app.core.i18n.errors import (  # noqa: E402,F401
    I18nError as ASRProviderError,
    SessionConcurrentLimitError as ConcurrentLimitError,
    SessionIllegalTransitionError as IllegalTransitionError,
)


class DomainError(Exception):
    """领域异常基类。"""


class AuthError(DomainError):
    """token 无效/缺失（WS 层捕获后回 error + 关闭；HTTP 层转 401）。"""


class SessionNotFound(DomainError):
    """会话不存在或非本人（资源隔离，不泄露存在性）。"""


class TemplateNotFound(DomainError):
    """模板不存在。"""


class LLMProviderError(DomainError):
    """LLM provider 调用失败（超时/重试耗尽/未配置）。"""
