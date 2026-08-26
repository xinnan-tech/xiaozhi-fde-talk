"""用户 Repository。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.db import SessionLocal
from app.persistence.models import User
from app.services.auth._pwd_ver_clock import next_pwd_ver_ts

# 内存缓存（user_id → (monotonic_ts, password_changed_at)）；TTL 60s。
# 简单 dict 不引外部依赖；大用户量场景后续可换 LRU + 事件失效。
_pwd_cache: dict[str, tuple[float, datetime | None]] = {}
_PWD_CACHE_TTL = 60.0


class UserRepository:
    """用户持久化。

    可选 session_factory：传入后 `*_auto` 方法可独立开/关 Session；
    不传则需在调用时显式给 db。多数业务通过 Depends(get_db) 走 db 入参。
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """按 username 查询；边界 .lower() 归一（防 MySQL utf8mb4_0900_ai_ci 撞库 + 跨方言一致）。"""
        return await self._get_by_username_raw(db, username.lower())

    async def _get_by_username_raw(self, db: AsyncSession, username: str) -> Optional[User]:
        res = await db.execute(select(User).where(User.username == username))
        return res.scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        return await db.get(User, user_id)

    async def get_pwd_changed_at(self, user_id: str) -> datetime | None:
        """读 password_changed_at；命中缓存直接返。

        缓存 TTL 60s——p99 改密场景下旧 token 最长可活 60s；安全性由前端
        主动跳到登录页兜底。改密路径（update_password / update_password_auto）
        会显式 _pwd_cache.pop 让吊销即时生效。
        """
        cached = _pwd_cache.get(user_id)
        if cached is not None:
            ts, value = cached
            if time.monotonic() - ts < _PWD_CACHE_TTL:
                return value
        async with SessionLocal() as db:
            row = await db.get(User, user_id)
            value = row.password_changed_at if row else None
        _pwd_cache[user_id] = (time.monotonic(), value)
        return value

    async def create(
        self, db: AsyncSession, username: str, password_hash: str, *, role: str = "user"
    ) -> User:
        """新建用户。

        边界 .lower() 归一 username（与 get_by_username 对齐——防 MySQL 默认
        collation 撞库 + 跨方言一致）。
        不在内部 commit——由调用方控制事务边界（register_user 整段需要 dialect 锁
        包住 count + insert，提前 commit 会让 PG pg_advisory_xact_lock 提前释放，
        失去并发首注册双 admin 防护）。
        """
        user = User(
            id=str(uuid.uuid4()),
            username=username.lower(),
            password_hash=password_hash,
            password_changed_at=next_pwd_ver_ts(),
            role=role,
        )
        db.add(user)
        await db.flush()  # 让 INSERT 落库 + 触发 unique 约束（IntegrityError 抛给调用方）
        # 新建用户不在缓存中——无需主动失效；下次 get_pwd_changed_at 自然落库
        return user

    async def update_password(self, db: AsyncSession, user_id: str, password_hash: str) -> None:
        """直接改 password_hash + 刷 password_changed_at + 失效缓存（→ 旧 token 立即吊销）。"""
        row = await db.get(User, user_id)
        if row is None:
            return
        row.password_hash = password_hash
        row.password_changed_at = next_pwd_ver_ts()
        await db.commit()
        _pwd_cache.pop(user_id, None)

    async def update_password_auto(self, username: str, plain_password: str) -> bool:
        """独立 Session：按 username 改密码（自动 hash）+ 刷 password_changed_at + 失效缓存。

        返回 True = 已更新；False = 用户不存在。
        用于 admin 改密端点等"调用方未持有 Session"的场景。
        """
        if self._session_factory is None:
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
            row.password_changed_at = next_pwd_ver_ts()
            await db.commit()
        # 失效缓存 → 旧 token pwd_ver 不匹配 → 立即吊销
        _pwd_cache.pop(row.id, None)
        return True


# 全局默认实例（无 session_factory；调用方需自传 db 或走 *_auto 会自动用 SessionLocal）
user_repo = UserRepository()
