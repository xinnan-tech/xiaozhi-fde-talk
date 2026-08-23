"""admin 用户管理：列用户。

路由 prefix 是相对 routes/__init__.py 的 APIRouter(prefix="/api/v1")，
最终路径为 /api/v1/admin/users。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth import CurrentUser
from app.persistence.db import get_db
from app.persistence.models import User
from app.transport.http.dependencies import require_admin
from app.transport.http.schemas import AdminUserInfo

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
