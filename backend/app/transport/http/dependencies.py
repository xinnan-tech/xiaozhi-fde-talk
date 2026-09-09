"""FastAPI 依赖（HTTP 适配）。

verify_token 逻辑用 transport/base.py:extract_auth（协议无关）。

优先级：HttpOnly cookie ``authorized-token`` > Authorization: Bearer header。
- 真实前端走 cookie 鉴权（withCredentials=true + 服务端 Set-Cookie HttpOnly）。
- 兼容路径保留 Authorization header（测试 / 老客户端 / 脚本）。
- 两者都没有 → 401。

注意：401 路径（缺 token / token 解析失败）**故意保留裸 HTTPException**，
不带 `code` 字段——前端 axios 拦截器靠 `!hasCode` 判定"凭证失效"以清 token
+ 跳登录。一旦这处加 `code`，会被误判为业务 401，破坏契约。详见
`docs/http-api.md` §3.4 / §5。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AuthError
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.transport.base import extract_auth

# auto_error=False：无 token 时由我们返回 401（而非默认 403）
_bearer = HTTPBearer(auto_error=None)


def _extract_token_from_request(request: Optional[Request]) -> Optional[str]:
    """从 cookie（首选）或 Authorization 头取 access_token。

    cookie 优先：HttpOnly cookie 是 XSS 安全的载体，浏览器自动带；Authorization
    头是 JS 可读的，仅作为兼容路径（脚本 / 外部调用 / 测试）。

    request 为 None 走"无 HTTP 上下文"分支（直接调依赖函数做单测的覆写），返
    None 让调用方按"无 token"处理——不抛 AttributeError 破坏可选鉴权契约。
    """
    if request is not None:
        cookie_token = request.cookies.get("authorized-token")
        if cookie_token:
            return cookie_token
    # Authorization 头：可能存在（HTTPAuthorizationCredentials 由 _bearer 解析）。
    # 即使无 request 也要走这一步——直接传 credentials=... 调依赖函数时，
    # request 缺失但 Authorization 头仍可能解析出 token（单测覆写路径）。
    auth_header = request.headers.get("Authorization") if request is not None else None
    if auth_header and auth_header.startswith("Bearer "):
        token_part = auth_header[7:].strip()
        if token_part:
            return token_part
    return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    token = _extract_token_from_request(request)
    if token is None and credentials is not None:
        # HTTPBearer 仍可能解析出（即便 _extract_token_from_request 没拿到），
        # 比如某些代理吞掉 cookie 但保留 Authorization 头的情况。
        token = credentials.credentials
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await extract_auth(token)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[CurrentUser]:
    """可选鉴权：无 token / token 解析失败都返回 None，不抛 401。

    给"全员可访问、登录用户额外返更多信息"的端点用（如 /version：匿名返
    200 + 空版本号，已登录返真实版本号）。

    直接调函数（单测覆写）时 credentials 仍是 ``Depends(...)`` 而非解析后的
    实例——按"无 token"分支返回 None，不访问 credentials 字段。
    """
    token = _extract_token_from_request(request)
    if (
        token is None
        and isinstance(credentials, HTTPAuthorizationCredentials)
    ):
        token = credentials.credentials
    if not token:
        return None
    try:
        return await extract_auth(token)
    except AuthError:
        return None


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """要求 admin 角色。非 admin 抛 I18nError → 403 + code=http.admin.required。"""
    if user.role != "admin":
        raise I18nError(Keys.HTTP_ADMIN_REQUIRED, http_status=403)
    return user