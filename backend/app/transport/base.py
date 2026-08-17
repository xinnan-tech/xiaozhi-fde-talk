"""传输层基础抽象（多协议接缝）。

Connection 抽象 + Metadata + Capabilities，让会话层与传输协议解耦。
Auth 边界：extract_auth 协议无关鉴权，WS 等非 HTTP 协议复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from app.core.exceptions import AuthError
from app.domain.auth import CurrentUser
from app.services.auth.token import decode_token


# ─────────────── 协议无关鉴权 ───────────────

def extract_auth(raw_token: Optional[str]) -> CurrentUser:
    """解析 `Bearer xxx` 或裸 token，返回当前用户。失败抛 AuthError。

    HTTP 中间件与 WS hello.token 共用此函数。
    """
    if not raw_token:
        raise AuthError("missing token")
    cred = raw_token[7:] if raw_token.startswith("Bearer ") else raw_token
    if not cred:
        raise AuthError("missing token")
    try:
        payload = decode_token(cred)
    except Exception as e:
        raise AuthError("invalid or expired token") from e
    return CurrentUser(
        user_id=payload.get("sub", ""),
        username=payload.get("username", ""),
        role=payload.get("role", "user"),
    )


# ─────────────── Connection 抽象 ───────────────

@dataclass(frozen=True)
class ConnectionMetadata:
    """多协议可观测性必备。"""
    protocol: Literal["ws", "mqtt", "udp", "quic", "http"]
    peer_addr: str
    client_id: Optional[str] = None
    connected_at: float = 0.0


@dataclass(frozen=True)
class ConnectionCapabilities:
    """协议能力声明——告诉 Runtime 自身可靠性语义。"""
    reliability: Literal["at_most_once", "at_least_once", "ordered", "exactly_once"] = "ordered"
    supports_resume: bool = False
    supports_backpressure: bool = False
    max_payload_bytes: int = 0


class Connection(Protocol):
    """协议无关的连接抽象。v1 由 transport/websocket/handler.py 实现。"""

    conn_id: str
    session_id: Optional[str]       # 未 bind 时 None

    @property
    def metadata(self) -> ConnectionMetadata: ...

    @property
    def capabilities(self) -> ConnectionCapabilities: ...

    @property
    def is_closed(self) -> bool: ...

    async def send(self, event: dict) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...
