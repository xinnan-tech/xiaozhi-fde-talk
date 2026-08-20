"""协议常量 / WS 消息类型。

把散落的字符串字面量集中，避免魔法字符串。
"""
from __future__ import annotations

from enum import StrEnum

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


class WsError(StrEnum):
    """WS error.code wire 字符串（StrEnum：每个成员的 .value 即 wire 码）。

    13 个 wire 码必须全部在 _WS_ERROR_KEY 中有映射；新增时同时更新
    _WS_ERROR_KEY 和 i18n catalogs（en_US.json / zh_CN.json / zh_TW.json）。
    """
    BAD_HANDSHAKE = "bad_handshake"
    AUTH_FAILED = "auth_failed"
    NOT_FOUND = "not_found"
    CONCURRENT_LIMIT = "concurrent_limit"
    BAD_JSON = "bad_json"
    INTERNAL = "internal"
    HANDSHAKE_TIMEOUT = "handshake_timeout"
    FRAME_TOO_LARGE = "frame_too_large"
    SESSION_ENDED = "session_ended"
    ASR_UNAVAILABLE = "asr_unavailable"
    CONNECTION_CONFLICT = "connection_conflict"
    CONNECTION_KICKED = "connection_kicked"
    AUDIO_LOW_LEVEL = "audio_low_level"


# ─────────────── coaching phase ───────────────

class CoachingPhase:
    RECOMPUTING = "recomputing"
    PARTIAL = "partial"
    FINAL = "final"


# ─────────────── HTTP 路径前缀 ───────────────

API_V1_PREFIX = "/api/v1"
WS_V1_PREFIX = "/ws/v1"


# ─────────────── WS 错误码 → i18n key 映射 ───────────────
# Wire code → i18n key map. Kept separate from the WsError enum value so that
# `WsError.NOT_FOUND.value == "not_found"` comparisons in tests/transports
# continue to work unchanged. Values reference `Keys` enum members (added in
# T01) rather than bare strings, so a typo here fails fast at import time
# instead of producing a `KeyError` at runtime when t() is called.
from app.core.i18n.messages import Keys  # noqa: E402

_WS_ERROR_KEY: dict[str, str] = {
    "bad_handshake":       Keys.WS_BAD_HANDSHAKE.value,
    "auth_failed":         Keys.WS_AUTH_FAILED.value,
    "not_found":           Keys.WS_SESSION_NOT_FOUND.value,
    "concurrent_limit":    Keys.WS_SESSION_CONCURRENT_LIMIT.value,
    "bad_json":            Keys.WS_BAD_HANDSHAKE_INVALID_JSON.value,
    "internal":            Keys.WS_INTERNAL.value,
    "handshake_timeout":   Keys.WS_HANDSHAKE_TIMEOUT.value,
    "frame_too_large":     Keys.WS_FRAME_TOO_LARGE.value,
    "session_ended":       Keys.WS_SESSION_ENDED.value,
    "asr_unavailable":     Keys.WS_ASR_UNAVAILABLE.value,
    "connection_conflict": Keys.WS_CONNECTION_CONFLICT.value,
    "connection_kicked":   Keys.WS_CONNECTION_KICKED.value,
    "audio_low_level":     Keys.WS_AUDIO_LOW_LEVEL.value,
}
