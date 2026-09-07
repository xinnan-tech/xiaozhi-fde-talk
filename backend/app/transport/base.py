"""传输层基础抽象（多协议接缝）。

Connection 抽象 + Metadata + Capabilities，让会话层与传输协议解耦。
Auth 边界：extract_auth 协议无关鉴权，WS 等非 HTTP 协议复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Literal, Optional, Protocol

from app.core.exceptions import AuthError
from app.domain.auth import CurrentUser
from app.persistence.repositories.user import user_repo
from app.services.auth.token import decode_token


# ─────────────── 协议无关鉴权 ───────────────

def token_from_subprotocols(subprotocols: Optional[list[str]]) -> Optional[str]:
    """从 Sec-WebSocket-Protocol 列表里挑出 bearer.<token>，无则 None。"""
    for sp in subprotocols or []:
        if sp.startswith("bearer."):
            return sp[len("bearer."):]
    return None


async def extract_auth(raw_token: Optional[str]) -> CurrentUser:
    """解析 `Bearer xxx` 或裸 token，比对 DB password_changed_at，返回当前用户。

    失败抛 AuthError。HTTP dependency + WS hello.token 共用。
    改密后旧 token 的 pwd_ver 与 DB 不一致 → 立即吊销。
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
    user_id = payload.get("sub", "")
    if not user_id:
        raise AuthError("missing sub")
    pwd_ver_claim = payload.get("pwd_ver")
    if pwd_ver_claim is None:
        raise AuthError("token missing pwd_ver")
    pwd_changed_at = await user_repo.get_pwd_changed_at(user_id)
    if pwd_changed_at is None:
        raise AuthError("user not found")
    # SQLite + SQLAlchemy ORM 往返丢 tz：写入是 aware UTC，存为 naive 字符串，
    # 读出来 tzinfo=None。统一当 UTC 解释，避免不同系统时区下 pwd_ver 计算漂移
    # 导致「改密后 token 应被吊销却放行」(CI UTC 下) 或「未改密却误吊销」
    # (mac 等本地非 UTC 系统)。
    if pwd_changed_at.tzinfo is None:
        pwd_changed_at = pwd_changed_at.replace(tzinfo=timezone.utc)
    if int(pwd_changed_at.timestamp()) != int(pwd_ver_claim):
        raise AuthError("token revoked (pwd_ver mismatch)")
    return CurrentUser(
        user_id=user_id,
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
