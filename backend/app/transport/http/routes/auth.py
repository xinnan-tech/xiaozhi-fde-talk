"""鉴权路由。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_store import get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.retry import RateLimiter
from app.persistence.db import get_db
from app.persistence.models import User
from app.persistence.repositories.user import user_repo
from app.services.auth.service import authenticate_user
from app.services.auth.token import create_access_token
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import (
    LoginRequest,
    LoginResponse,
    RegistrationStatusResponse,
    UserInfo,
)
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
    pwd_changed_at = await user_repo.get_pwd_changed_at(user.user_id)
    # 历史用户 password_changed_at 可能为 None（迁移前回填的边缘场景）；
    # 退化到当前时间——保证 token 必然签出，pwd_ver 与 DB 始终能比对。
    pwd_ver = int(pwd_changed_at.timestamp()) if pwd_changed_at else int(time.time())
    token = await create_access_token(
        subject=user.user_id,
        pwd_ver=pwd_ver,
        extra={"username": user.username, "role": user.role},
    )
    return LoginResponse(
        access_token=token,
        user=UserInfo(id=user.user_id, username=user.username, role=user.role),
    )


@router.get("/auth/registration-status", response_model=RegistrationStatusResponse)
async def registration_status(db: AsyncSession = Depends(get_db)) -> RegistrationStatusResponse:
    """公开端点：零用户强制 allow_registration=true（首用户注册路径必须通畅）；
    有用户时按 auth.allow_registration key 当前值返。

    响应体仅暴露 allow_registration，不暴露 user_count / has_admin（防侦察）。
    接口失败 / 超时由前端降级显示"暂不可用，请稍后重试"。
    """
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if count == 0:
        return RegistrationStatusResponse(allow_registration=True)
    cfg_val = await get_config_store().get("auth.allow_registration")
    return RegistrationStatusResponse(allow_registration=(cfg_val == "true"))
