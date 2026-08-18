"""协议常量 / WS 消息类型。

把散落的字符串字面量集中，避免魔法字符串。
"""
from __future__ import annotations

# ─────────────── WS 消息类型 ───────────────

class WsMsgType:
    """客户端 → 服务端。"""
    HELLO = "hello"
    LISTEN = "listen"
    COACHING_SKIP = "coaching.skip"
    COACHING_IGNORE = "coaching.ignore"
    SESSION_TOUCH = "session.touch"


class WsEventType:
    """服务端 → 客户端。"""
    HELLO = "hello"
    ASR = "asr"
    COACHING_UPDATE = "coaching.update"
    SESSION_ENDED = "session.ended"
    ERROR = "error"
    SNAPSHOT = "snapshot"


class WsError:
    """WS error.code 枚举。"""
    BAD_HANDSHAKE = "bad_handshake"
    AUTH_FAILED = "auth_failed"
    NOT_FOUND = "not_found"
    CONCURRENT_LIMIT = "concurrent_limit"
    BAD_JSON = "bad_json"
    INTERNAL = "internal"


# ─────────────── coaching phase ───────────────

class CoachingPhase:
    RECOMPUTING = "recomputing"
    PARTIAL = "partial"
    FINAL = "final"


# ─────────────── HTTP 路径前缀 ───────────────

API_V1_PREFIX = "/api/v1"
WS_V1_PREFIX = "/ws/v1"
