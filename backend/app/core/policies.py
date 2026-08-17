"""会话/连接策略对象（可配，不硬编码）。

60s 宽限、出站缓冲大小、去抖窗口等运行时参数，支持按协议覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionPolicy:
    """会话存活与辅导触发策略。"""
    liveness_window_s: float = 60.0          # 存活窗口（断连后保留 Runtime 的时长）
    outbound_buffer_size: int = 100          # 出站缓冲大小
    outbound_buffer_ttl_s: float = 300.0     # 缓冲 TTL
    idempotency_window_s: float = 300.0      # 幂等窗口
    transcript_soft_limit: int = 500         # transcript 软上限（超限截断最早段）


# 默认策略（从 settings 注入，见 app.py composition root）
DEFAULT_SESSION_POLICY = SessionPolicy()

# 按协议覆盖
PROTOCOL_POLICIES: dict[str, SessionPolicy] = {
    "ws": SessionPolicy(liveness_window_s=60.0),
}


def get_policy(protocol: str = "ws") -> SessionPolicy:
    return PROTOCOL_POLICIES.get(protocol, DEFAULT_SESSION_POLICY)
