"""HttpOnly cookie 工具。

accessToken / refreshToken 从响应体迁移到 HttpOnly + Secure cookie，让 JS 读不到
token 明文——同源 XSS 即便拿到执行权，也无法 ``document.cookie`` 拿 JWT。

为什么不放 Authorization header：
  Authorization header 同样可被 XSS 读到（``XMLHttpRequest.setRequestHeader``
  或 fetch headers 都是 JS 可见的）。HttpOnly cookie 是唯一「JS 物理不可读」
  的载体。

Secure 与 SameSite 选择：
  - Secure：prod 强制 true（HTTPS only）；dev/test 关闭（http://localhost 不支持）。
  - SameSite=Lax：access cookie，宽松策略下也禁掉任何跨站请求自动附；
    顶层 GET 仍然带，但跨站 POST / iframe / 第三方子资源不带。
  - SameSite=Strict：refresh cookie 最严，禁掉所有跨站请求自动附。

max_age：access cookie 走 jwt_expire_minutes，refresh cookie 走
refresh_token_expire_days。配置变更后用配置值，覆盖默认 cookie 寿命——保证
后端 TTL 与 cookie 寿命对齐，避免 cookie 还在但 token 已过期（或反之）。

config_store 异常兜底：get_auth_runtime_config() 走 DB 查询，DB 短暂不可用
或 lifespan warm 未完成会抛错。config_store 抛错时回退到 settings 直读
env 默认值——保证 Set-Cookie 仍能正常下发（否则 login/register/refresh
会被炸 500，refresh 死循环）。
"""
from __future__ import annotations

import logging

from fastapi import Response

from app.core.config_store import get_auth_runtime_config
from app.core.settings import get_settings

_log = logging.getLogger(__name__)

# Cookie 名：与前端保持一致（前端通过 ``document.cookie`` 看不到 HttpOnly 内容，
# 但 logout / login 后端清 cookie 时仍走同 key）。
ACCESS_TOKEN_COOKIE = "authorized-token"
REFRESH_TOKEN_COOKIE = "refresh-token"


def _secure_flag() -> bool:
    """Secure 仅在 prod 开启。dev/test 跑 http://localhost：设 Secure 后浏览器
    直接拒发 cookie，连登录都登不上。
    """
    return get_settings().env == "prod"


async def _refresh_cookie_max_age() -> int:
    """refresh cookie max_age，按 refresh_token_expire_days 配置（秒）。
    async 因为 config_store 是异步接口。

    config_store 抛错时回退到 settings 默认值——保证 Set-Cookie 不被炸 500。
    """
    try:
        cfg = await get_auth_runtime_config()
        return cfg["refresh_token_expire_days"] * 24 * 60 * 60
    except Exception:
        _log.warning(
            "config_store 不可用，refresh cookie max_age 退化到 settings 默认值",
            exc_info=True,
        )
        return get_settings().refresh_token_expire_days * 24 * 60 * 60


async def set_access_cookie(response: Response, access_token: str) -> None:
    """只写 access_token cookie（/auth/refresh 后用）。max_age 跟 access TTL。"""
    try:
        cfg = await get_auth_runtime_config()
        max_age = cfg["jwt_expire_minutes"] * 60
    except Exception:
        _log.warning(
            "config_store 不可用，access cookie max_age 退化到 settings 默认值",
            exc_info=True,
        )
        max_age = get_settings().jwt_expire_minutes * 60
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=max_age,
        httponly=True,
        secure=_secure_flag(),
        samesite="lax",
        path="/",
    )


async def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """只写 refresh_token cookie（login/register 用）。max_age 跟 refresh TTL。"""
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=await _refresh_cookie_max_age(),
        httponly=True,
        secure=_secure_flag(),
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """清两个 cookie。max_age=0 + path 必须与写入时一致，否则浏览器不会真删。

    不需要 secure flag：delete 走响应头 Set-Cookie 即可；浏览器接到带过期
    时间 + 同 path 即视为清除。
    """
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/")