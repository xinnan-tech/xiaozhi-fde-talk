"""数据库初始化不应删除真实管理员账户。"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence import bootstrap
from app.persistence.models import Base, User


@pytest.mark.asyncio
async def test_init_db_preserves_registered_admin(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(bootstrap, "engine", engine)
    monkeypatch.setattr(bootstrap, "SessionLocal", session_local)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("APP_DB_USE_ALEMBIC", raising=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_local() as session:
            session.add(User(id="u1", username="admin", password_hash="x", role="admin"))
            await session.commit()

        await bootstrap.init_db()

        async with session_local() as session:
            user = (await session.execute(
                select(User).where(User.username == "admin")
            )).scalar_one()
            assert user.role == "admin"
    finally:
        await engine.dispose()
