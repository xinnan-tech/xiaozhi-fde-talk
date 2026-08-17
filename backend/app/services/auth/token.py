"""JWT 签发 / 验证（纯工具，无 IO）。

配置走 core/settings（jwt_secret/jwt_algorithm 是 A 类） +
core/config_store（jwt_expire_minutes 是 B 类）。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from app.core.config_store import get_auth_runtime_config
from app.core.settings import get_settings

# 签发 / 验签共享的固定值：算法白名单与受众/签发方。
# decode 用硬白名单，绝不读 settings.jwt_algorithm——避免 env 误配（如
# JWT_ALGORITHM=none）绕过签名校验。audience 在 create/decode 必须一致，
# 提为常量避免两处字面量漂移导致静默全量鉴权失败。
_SIGNING_ALG = "HS256"
_AUDIENCE = "xiaozhi-client"
_ISSUER = "xiaozhi-fde-talk"


async def create_access_token(subject: str, extra: Optional[dict[str, Any]] = None) -> str:
    """异步签名 token：从 ConfigStore 读 jwt_expire_minutes。"""
    settings = get_settings()
    cfg = await get_auth_runtime_config()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=cfg["jwt_expire_minutes"]),
        "jti": secrets.token_urlsafe(16),
        "iss": _ISSUER,
        "aud": _AUDIENCE,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=_SIGNING_ALG)


def decode_token(token: str) -> dict[str, Any]:
    """解码 + 验签（用 A 类静态配置）。"""
    settings = get_settings()
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[_SIGNING_ALG],
        audience=_AUDIENCE,
        issuer=_ISSUER,
    )