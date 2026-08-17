"""领域异常：跨层复用的业务错误类型。

transport 层可统一异常处理（exception_handlers.py）而不依赖具体业务模块。
"""
from __future__ import annotations


class DomainError(Exception):
    """领域异常基类。"""


class AuthError(DomainError):
    """token 无效/缺失（WS 层捕获后回 error + 关闭；HTTP 层转 401）。"""


class ConcurrentLimitError(DomainError):
    """全局活跃访谈数已达上限（session.max_concurrent，= FunASR 房间容量）。

    活跃指 setting_up / in_progress（持有 live 运行时）；suspended 不占名额。
    """


class IllegalTransitionError(DomainError):
    """非法状态转换。"""


class SessionNotFound(DomainError):
    """会话不存在或非本人（资源隔离，不泄露存在性）。"""


class TemplateNotFound(DomainError):
    """模板不存在。"""


class LLMProviderError(DomainError):
    """LLM provider 调用失败（超时/重试耗尽/未配置）。"""


class ASRProviderError(DomainError):
    """ASR provider 连接/初始化失败（服务未启动 / ws_url 错误 / TLS 失败等）。"""
