"""传输层基础抽象（多协议接缝）。

Connection 抽象 + Metadata + Capabilities，让会话层与传输协议解耦。
Auth 边界：extract_auth 协议无关鉴权，WS 等非 HTTP 协议复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Literal, Mapping, Optional, Protocol

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


def token_from_ws_handshake(
    cookies: Mapping[str, str],
    subprotocols: Optional[list[str]],
) -> Optional[str]:
    """WS 握手阶段取 access_token：

    1. HttpOnly cookie ``authorized-token`` —— 浏览器主路径，WS upgrade 时
       自动附 Cookie 头，FastAPI 解析到 ``ws.cookies``。
    2. ``bearer.<jwt>`` Sec-WebSocket-Protocol —— 脚本 / chaos 客户端兜底。

    都无 → None，调用方按 AuthError 拒握。两条路径不要在 WS handler 各自
    复制实现——HttpOnly cookie 迁移后所有 WS（interview / asr / ...）
    必须走同款顺序，否则浏览器用户在某条路径下永远 1006 拒握。"""
    cookie_token = cookies.get("authorized-token")
    if cookie_token:
        return cookie_token
    return token_from_subprotocols(subprotocols)


def offered_subprotocol_for_token(
    token: Optional[str],
    subprotocols: Optional[list[str]],
) -> Optional[str]:
    """WS accept 时回传给客户端的 subprotocol。

    仅当客户端**明确**发了 ``bearer.*`` subprotocol 时才回传 ``bearer.<token>``，
    让脚本 / chaos 客户端能验明用的是哪条路径。客户端没发 subprotocol（cookie
    路径）时返回 None——浏览器不接受未请求的 subprotocol，传 ``bearer.xxx``
    会触发协议违规 close。"""
    if not token:
        return None
    if any(sp.startswith("bearer.") for sp in subprotocols or []):
        return "bearer." + token
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
