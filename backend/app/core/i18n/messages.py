from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path


_DATA_DIR = Path(__file__).parent / "data"


class Keys(StrEnum):
    # ---- HTTP routes ----
    HTTP_AUTH_RATE_LIMITED = "http.auth.rate_limited"
    HTTP_AUTH_INVALID_CREDENTIALS = "http.auth.invalid_credentials"
    HTTP_TEMPLATE_NOT_FOUND = "http.template.not_found"
    HTTP_SESSION_NOT_FOUND = "http.session.not_found"
    HTTP_SESSION_TITLE_DEFAULT = "http.session.title.default"
    HTTP_UNKNOWN_STATUS = "http.session.unknown_status"
    HTTP_REPORT_NOT_READY = "http.report.not_ready"
    HTTP_REPORT_FORMAT_UNSUPPORTED = "http.report.format_unsupported"

    # ---- WebSocket frames ----
    WS_INTERNAL = "ws.internal"
    WS_HANDSHAKE_TIMEOUT = "ws.handshake.timeout"
    WS_BAD_HANDSHAKE = "ws.bad_handshake"
    WS_BAD_HANDSHAKE_JSON = "ws.bad_handshake.expect_json"
    WS_BAD_HANDSHAKE_ORDER = "ws.bad_handshake.expect_hello_first"
    WS_BAD_HANDSHAKE_INVALID_JSON = "ws.bad_handshake.invalid_json"
    WS_AUTH_FAILED = "ws.auth.failed"
    WS_FRAME_TOO_LARGE = "ws.frame.too_large"
    WS_SESSION_CONCURRENT_LIMIT = "ws.session.concurrent_limit"
    WS_SESSION_NOT_FOUND = "ws.session.not_found"
    WS_SESSION_ENDED = "ws.session.ended"
    WS_ASR_UNAVAILABLE = "ws.asr.unavailable"
    WS_ASR_DISCONNECTED = "ws.asr.disconnected"
    WS_ASR_CONNECT_FAIL = "ws.asr.connect_fail"
    WS_CONNECTION_CONFLICT = "ws.connection.conflict"
    WS_CONNECTION_KICKED = "ws.connection.kicked"
    WS_AUDIO_LOW_LEVEL = "ws.audio.low_level"
    WS_CLOSE_SESSION_ENDED = "ws.close.session_ended"
    WS_CLOSE_SUSPENDED = "ws.close.suspended"

    # ---- Sessions domain ----
    SESSION_CONCURRENT_LIMIT = "session.concurrent_limit"
    SESSION_ILLEGAL_TRANSITION = "session.illegal_transition"
    SESSION_EDIT_FORBIDDEN = "session.edit_forbidden"
    SESSION_DELETE_FORBIDDEN = "session.delete_forbidden"

    # ---- Reports ----
    REPORT_FORMAT_NOT_IMPLEMENTED = "report.format_not_implemented"

    # ---- LLM adapter ----
    LLM_NOT_CONFIGURED = "llm.not_configured"
    LLM_NON_RETRYABLE = "llm.non_retryable"
    LLM_RETRY_EXHAUSTED = "llm.retry_exhausted"
    LLM_NO_JSON_BLOCK = "llm.no_json_block"
    LLM_INVALID_JSON = "llm.invalid_json"
    LLM_SCHEMA_MISMATCH = "llm.schema_mismatch"
    LLM_TIMEOUT = "llm.timeout"

    # ---- ASR adapter ----
    ASR_URL_NOT_CONFIGURED = "asr.url_not_configured"
    ASR_CONNECT_FAIL = "asr.connect_fail"
    ASR_DEAD = "asr.dead"
    ASR_FEED_FAIL = "asr.feed_fail"

    # ---- Diagnostics (LLM) ----
    DIAG_LLM_CONFIG_MISSING = "diag.llm.config_missing"
    DIAG_LLM_CONFIG_MISSING_RAW = "diag.llm.config_missing_raw"
    DIAG_LLM_UNREACHABLE = "diag.llm.unreachable"
    DIAG_LLM_INVOKE_FAIL = "diag.llm.invoke_fail"
    DIAG_LLM_AUTH_FAIL = "diag.llm.auth_fail"
    DIAG_LLM_RATE_LIMIT = "diag.llm.rate_limit"
    DIAG_LLM_BAD_CONFIG = "diag.llm.bad_config"
    DIAG_LLM_SERVICE_FAIL = "diag.llm.service_fail"
    DIAG_LLM_UNREACHABLE_TYPED = "diag.llm.unreachable_typed"
    DIAG_LLM_INVOKE_FAIL_TYPED = "diag.llm.invoke_fail_typed"
    DIAG_LLM_OK_BUT_EMPTY = "diag.llm.ok_but_empty"
    DIAG_LLM_OK = "diag.llm.ok"

    # ---- Diagnostics (ASR) ----
    DIAG_ASR_TIMEOUT = "diag.asr.timeout"
    DIAG_ASR_UNREACHABLE = "diag.asr.unreachable"
    DIAG_ASR_TLS_FAIL = "diag.asr.tls_fail"
    DIAG_ASR_BAD_URL = "diag.asr.bad_url"
    DIAG_ASR_INVOKE_FAIL_TYPED = "diag.asr.invoke_fail_typed"
    DIAG_ASR_NOT_CONFIGURED = "diag.asr.not_configured"
    DIAG_ASR_DEAD = "diag.asr.dead"
    DIAG_ASR_NO_RESULT = "diag.asr.no_result"
    DIAG_ASR_OK = "diag.asr.ok"

    # ---- Startup / settings / secrets ----
    STARTUP_ADMIN_PASSWORD_MISSING = "startup.admin_password_missing"
    STARTUP_DATABASE_MIGRATION_FAIL = "startup.database_migration_fail"
    SETTINGS_PROD_NO_SQLITE = "settings.prod_no_sqlite"
    SECRET_RESOLVE_FAILED = "secret.resolve_failed"

    # ---- Password policy ----
    PASSWORD_TOO_SHORT = "password.too_short"
    PASSWORD_TOO_SHORT_MIN = "password.too_short_min"
    PASSWORD_TOO_LONG = "password.too_long"
    PASSWORD_TOO_WEAK = "password.too_weak"

    # ---- Config validation ----
    CONFIG_INVALID_ENUM_VALUE = "config.invalid_enum_value"


@lru_cache(maxsize=1)
def load_catalogs() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(_DATA_DIR.glob("*.json")):
        locale = path.stem.replace("_", "-")
        with path.open(encoding="utf-8") as f:
            out[locale] = json.load(f)
    return out


def reload_catalogs() -> dict[str, dict[str, str]]:
    """Force-reload every catalog from disk and refresh the lru_cache.

    Use this in tests that intentionally mutate the in-memory catalog and then
    need `load_catalogs()` to return the mutated state. Production code should
    call `load_catalogs()` directly — the cache is hot for the lifetime of the
    process and catalogs are static on disk.
    """
    load_catalogs.cache_clear()
    return load_catalogs()