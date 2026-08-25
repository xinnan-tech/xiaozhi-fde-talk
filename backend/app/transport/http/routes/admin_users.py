"""admin 用户管理：列用户 / 重置密码。

路由 prefix 是相对 routes/__init__.py 的 APIRouter(prefix="/api/v1")，
最终路径为 /api/v1/admin/users 与 /api/v1/admin/users/{user_id}/password。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.password_policy import validate_password_strength
from app.domain.auth import CurrentUser
from app.persistence.db import get_db
from app.persistence.models import User
from app.persistence.repositories.user import _pwd_cache
from app.transport.http.dependencies import require_admin
from app.transport.http.schemas import AdminResetPasswordRequest, AdminUserInfo

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.get("", response_model=list[AdminUserInfo])
async def list_users(
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserInfo]:
    """列出全部用户（不含 password_hash）。"""
    rows = (await db.execute(select(User))).scalars().all()
    return [
        AdminUserInfo(
            id=u.id,
            username=u.username,
            role=u.role,
            created_at=_iso(u.created_at),
            password_changed_at=_iso(u.password_changed_at),
        )
        for u in rows
    ]


@router.post("/{user_id}/password")
async def reset_password(
    user_id: str,
    body: AdminResetPasswordRequest,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """重置用户密码。同步刷新 password_changed_at，旧 token 立即失效。

    单 session 路径：复用请求级 get_db；之前嵌套开 SessionLocal 调
    update_password_auto 会让外层 session 的隐式事务与内层 commit
    在 SQLite 上时序不稳——CI 偶发旧 token pwd_ver 仍命中缓存里的旧值，
    吊销检查放行 → 403 而非 401。

    不限制 admin 改其他 admin 的密码——admin 数量本来就少，最低门槛 1 个
    即可恢复（自助注册关时人工种子仍可用 service 层 register_user 走后续任务）。
    """
    from app.core.security import hash_password_async
    validate_password_strength(body.new_password)
    row = await db.get(User, user_id)
    if row is None:
        raise I18nError(Keys.AUTH_USER_NOT_FOUND, http_status=404)
    new_hash = await hash_password_async(body.new_password)
    row.password_hash = new_hash
    row.password_changed_at = datetime.now(timezone.utc)
    await db.commit()
    _pwd_cache.pop(user_id, None)
    return {"ok": True}
