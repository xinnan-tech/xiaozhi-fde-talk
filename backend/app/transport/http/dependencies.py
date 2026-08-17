"""FastAPI 依赖（HTTP 适配）。

verify_token 逻辑用 transport/base.py:extract_auth（协议无关）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AuthError
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
        return extract_auth(credentials.credentials)
    except AuthError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """要求 admin 角色。"""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user
