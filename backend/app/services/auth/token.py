"""JWT 签发 / 验证（纯工具，无 IO）。

配置走 core/settings（jwt_secret/jwt_algorithm 是 A 类） +
core/config_store（jwt_expire_minutes 是 B 类）。

双 token 模型：
- access_token：短 TTL，承载鉴权会话（默认 1440 分钟 = 24h）
- refresh_token：长 TTL（默认 30 天），一次性使用（rotation）——
  /auth/refresh 每次签发新 refresh 并把旧 jti 置 rotated；
  旧 jti 在 grace 窗外再现视同泄露（reuse 检测 → 全家撤销）。
  jti 的会话状态在 persistence/repositories/refresh_session.py
  （DB 表 refresh_sessions，多 worker 共享、重启不丢）。
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

# token 类型声明：access 用于业务鉴权，refresh 只用于换 access；
# decode 后由调用方按 type 分发——避免 access token 被拿去刷 refresh（混用）。
_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"


async def create_access_token(
    subject: str,
    pwd_ver: int,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """异步签名 access token。

    pwd_ver 是 password_changed_at 的 Unix 秒戳——改密即吊销的对照值。
    extra 里的 role/username 仅为装饰（调试 / 日志参考），鉴权不信任——
    校验侧一律从 DB 取（transport/base.py::extract_auth）。
    """
    settings = get_settings()
    cfg = await get_auth_runtime_config()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": _TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(minutes=cfg["jwt_expire_minutes"]),
        "jti": secrets.token_urlsafe(16),
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "pwd_ver": int(pwd_ver),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=_SIGNING_ALG)


async def create_refresh_token(
    subject: str,
    pwd_ver: int,
    extra: Optional[dict[str, Any]] = None,
) -> tuple[str, str, datetime]:
    """签发 refresh token，返回 (token, jti, expires_at)。

    jti 单独返回供路由层在 logout 时撤销。refresh token 不能直接调业务接口——
    /auth/refresh 端点会校验 type=refresh + jti 未撤销后才换 access。
    extra 里的 role/username 仅为装饰（调试 / 日志参考），鉴权不信任——
    refresh 换新 access 时从 DB 取（routes/auth.py::refresh）。
    """
    settings = get_settings()
    cfg = await get_auth_runtime_config()
    now = datetime.now(timezone.utc)
    jti = secrets.token_urlsafe(16)
    expires_at = now + timedelta(days=cfg["refresh_token_expire_days"])
    payload: dict[str, Any] = {
        "sub": subject,
        "type": _TOKEN_TYPE_REFRESH,
        "iat": now,
        "exp": expires_at,
        "jti": jti,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "pwd_ver": int(pwd_ver),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=_SIGNING_ALG), jti, expires_at


def decode_token(token: str) -> dict[str, Any]:
    """解码 + 验签（用 A 类静态配置）。

    不强制 type claim——历史签出的 access token 没有 type 字段，兼容。
    需要按类型分发时由调用方自行 if payload.get("type") 判断。

    leeway=30s：吸收 NTP 漂移与本地时钟小幅不同步——若服务节点时钟偏差超过
    leeway，签发即报「签名过期」拒收。30s 是 iat/exp 容差默认，对正常
    容器 / VM 时钟足够宽松。
    """
    settings = get_settings()
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[_SIGNING_ALG],
        audience=_AUDIENCE,
        issuer=_ISSUER,
        leeway=30,
    )