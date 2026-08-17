"""用户 Repository。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import User


class UserRepository:
    """用户持久化。

    可选 session_factory：传入后 `*_auto` 方法可独立开/关 Session；
    不传则需在调用时显式给 db。多数业务通过 Depends(get_db) 走 db 入参。
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        res = await db.execute(select(User).where(User.username == username))
        return res.scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        return await db.get(User, user_id)

    async def create(self, db: AsyncSession, username: str, password_hash: str) -> User:
        import uuid
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=password_hash,
        )
        db.add(user)
        await db.commit()
        return user

    async def update_password(self, db: AsyncSession, user_id: str, password_hash: str) -> None:
        """直接改 password_hash。"""
        row = await db.get(User, user_id)
        if row is None:
            return
        row.password_hash = password_hash
        await db.commit()

    async def update_password_auto(self, username: str, plain_password: str) -> bool:
        """独立 Session：按 username 改 password_hash（自动 hash）。

        返回 True = 已更新；False = 用户不存在。
        用于 admin 改密端点等"调用方未持有 Session"的场景。
        """
        if self._session_factory is None:
            from app.persistence.db import SessionLocal
            factory = SessionLocal
        else:
            factory = self._session_factory

        from app.core.security import hash_password_async
        new_hash = await hash_password_async(plain_password)
        async with factory() as db:
            row = await self.get_by_username(db, username)
            if row is None:
                return False
            row.password_hash = new_hash
            await db.commit()
        return True


# 全局默认实例（无 session_factory；调用方需自传 db 或走 *_auto 会自动用 SessionLocal）
user_repo = UserRepository()