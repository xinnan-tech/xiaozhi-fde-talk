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
from app.persistence.db import SessionLocal, get_db
from app.persistence.models import User
from app.persistence.repositories.user import user_repo
from app.transport.http.dependencies import require_admin
from app.transport.http.schemas import AdminResetPasswordRequest, AdminUserInfo

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    # 确保转成 UTC 再序列化，保证前端 new Date() 能正确识别为 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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
) -> dict[str, bool]:
    """重置用户密码。同步刷新 password_changed_at，旧 token 立即失效。

    不限制 admin 改其他 admin 的密码——admin 数量本来就少，最低门槛 1 个
    即可恢复（自助注册关时人工种子仍可用 service 层 register_user 走后续任务）。
    """
    validate_password_strength(body.new_password)
    async with SessionLocal() as s:
        row = await s.get(User, user_id)
        if row is None:
            raise I18nError(Keys.AUTH_USER_NOT_FOUND, http_status=404)
        # 复用 update_password_auto：自带事务 + 写 password_changed_at + 失效缓存
        ok = await user_repo.update_password_auto(row.username, body.new_password)
    if not ok:
        raise I18nError(Keys.AUTH_USER_NOT_FOUND, http_status=404)
    return {"ok": True}
