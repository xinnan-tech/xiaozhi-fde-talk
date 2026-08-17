"""鉴权业务逻辑。

密码哈希用 core/security，用户查询走 Repository。
返回 domain.CurrentUser（不暴露 ORM User 到 services/transport）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password_async
from app.domain.auth import CurrentUser
from app.persistence.repositories.user import user_repo


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[CurrentUser]:
    user = await user_repo.get_by_username(db, username)
    if user is None or not await verify_password_async(password, user.password_hash):
        return None
    return CurrentUser(user_id=user.id, username=user.username, role=user.role or "user")
