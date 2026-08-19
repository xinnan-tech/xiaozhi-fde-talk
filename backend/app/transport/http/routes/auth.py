"""鉴权路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.retry import RateLimiter
from app.persistence.db import get_db
from app.services.auth.service import authenticate_user
from app.services.auth.token import create_access_token
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import LoginRequest, LoginResponse, UserInfo
from app.domain.auth import CurrentUser

router = APIRouter()

_login_limiter = RateLimiter(capacity=5, refill_per_hour=300)


def _client_ip(request: Request) -> str:
    """经反向代理（nginx 等）部署时，request.client.host 是代理地址：
    所有真实用户共享一个桶，一人刷爆全员 429。取可信的 X-Forwarded-For
    首跳；无该头（直连）回落到 socket 地址。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"{_client_ip(request)}:{req.username}"
    if not _login_limiter.try_acquire(key):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    user = await authenticate_user(db, req.username, req.password)
    if user is None:
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    token = await create_access_token(
        subject=user.user_id,
        extra={"username": user.username, "role": user.role},
    )
    return LoginResponse(
        access_token=token,
        user=UserInfo(id=user.user_id, username=user.username, role=user.role),
    )
