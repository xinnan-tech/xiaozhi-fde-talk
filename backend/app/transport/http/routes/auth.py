"""鉴权路由。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_store import get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.password_policy import validate_password_strength
from app.core.retry import RateLimiter
from app.core.security import verify_password_async
from app.persistence.db import get_db
from app.persistence.models import User
from app.persistence.repositories.user import user_repo
from app.services.auth.service import authenticate_user, register_user as svc_register
from app.services.auth.token import create_access_token
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
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


@router.post("/auth/register", response_model=LoginResponse)
async def register(
    req: RegisterRequest, db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """注册 + 自动登录（公开端点）。

    单一事务：先 `async with db.begin()`，再 `await svc_register(db, ...)`；
    register_user 内部不管理事务边界（dialect 锁 + count + insert 必须同事务）。

    SQLite 并发安全说明：SQLAlchemy 2 AsyncSession 不暴露 `execution_options`
    在依赖注入的 session 上（autobegin 后 isolation_level 不可改）；aiosqlite
    也不接受 SQLAlchemy 的 isolation_level 字面量。SQLite 路径靠 username
    unique 约束收口（duplicate → IntegrityError → 409）；"两请求都见 count=0"
    的双 admin 窗口极窄，生产建议 PG/MySQL。

    弱密码校验移到 service.register_user（保证 CLI / admin 代注册同受约束），
    本路由只做 confirm_password 比对。
    """
    if req.password != req.confirm_password:
        raise I18nError(Keys.AUTH_PASSWORD_MISMATCH, http_status=400)

    try:
        async with db.begin():
            current = await svc_register(db, req.username, req.password)
    except IntegrityError:
        await db.rollback()
        raise I18nError(Keys.AUTH_USERNAME_TAKEN, http_status=409)

    # 签发 token（含 pwd_ver，参考 login 路由 + Task 2 改密吊销约定）
    pwd_changed_at = await user_repo.get_pwd_changed_at(current.user_id)
    # 历史用户 password_changed_at 可能为 None；退化到当前时间——保证 token
    # 必然签出，pwd_ver 与 DB 始终能比对（login 路由同款）。
    pwd_ver = int(pwd_changed_at.timestamp()) if pwd_changed_at else int(time.time())
    token = await create_access_token(
        subject=current.user_id,
        pwd_ver=pwd_ver,
        extra={"username": current.username, "role": current.role},
    )
    return LoginResponse(
        access_token=token,
        user=UserInfo(id=current.user_id, username=current.username, role=current.role),
    )


@router.post("/auth/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """普通用户自助改密：验证旧密码 + 写新密码 + bump password_changed_at。

    不限 admin——任何持有效 token 的登录用户都能调。复用 user_repo.update_password_auto
    （自带事务 + 失效 _pwd_cache）→ 旧 token 的 pwd_ver 不匹配 → 立即吊销。

    旧密码错误 → 401；新密码强度不合规 → 400（validate_password_strength 抛 I18nError）。
    """
    user = await user_repo.get_by_id(db, current.user_id)
    if user is None or not await verify_password_async(body.old_password, user.password_hash):
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    validate_password_strength(body.new_password)
    # 走 update_password_auto：独立 Session + 刷 password_changed_at + _pwd_cache.pop
    # 复用 admin 改密端点同款路径，避免两条密码写路径并存导致行为漂移。
    ok = await user_repo.update_password_auto(user.username, body.new_password)
    if not ok:
        # 极窄边界：token 解析成功但 user 在此期间被删；返 401 提示重新登录。
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    return {"ok": True}
