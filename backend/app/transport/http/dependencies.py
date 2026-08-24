"""FastAPI 依赖（HTTP 适配）。

verify_token 逻辑用 transport/base.py:extract_auth（协议无关）。

注意：401 路径（缺 token / token 解析失败）**故意保留裸 HTTPException**，
不带 `code` 字段——前端 axios 拦截器靠 `!hasCode` 判定"凭证失效"以清 token
+ 跳登录。一旦这处加 `code`，会被误判为业务 401，破坏契约。详见
`docs/http-api.md` §3.4 / §5。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AuthError
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.transport.base import extract_auth

# auto_error=False：无 token 时由我们返回 401（而非默认 403）
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await extract_auth(credentials.credentials)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """要求 admin 角色。非 admin 抛 I18nError → 403 + code=http.admin.required。"""
    if user.role != "admin":
        raise I18nError(Keys.HTTP_ADMIN_REQUIRED, http_status=403)
    return user
