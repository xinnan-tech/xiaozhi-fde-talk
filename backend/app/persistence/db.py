"""数据库引擎 + Session 工厂。

ORM 表模型在 persistence/models.py；密码哈希在 core/security.py；
init_db / sweep 在 persistence/bootstrap.py。
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings


def _dumps(obj) -> str:
    """JSON 序列化保留中文明文（默认 ensure_ascii 会把中文转成 \\uXXXX）。"""
    return json.dumps(obj, ensure_ascii=False)


def _enable_sqlite_foreign_keys(engine) -> None:
    """为 SQLite 连接打开外键强制：每个新连接执行 PRAGMA foreign_keys=ON。

    SQLite 默认不强制外键约束，SQLAlchemy 也不会代为开启。若不开此 PRAGMA，
    models 里声明的 ondelete=CASCADE 形同虚设——删访谈时报告行不会被级联清除，
    成为孤儿数据。此处为每个新连接打开该 PRAGMA，使级联在运行时真正生效。
    非 SQLite 后端（MySQL/PG）默认即强制外键，直接跳过。
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def _build_engine():
    settings = get_settings()
    engine_kwargs = {
        "echo": settings.db_echo,
        "future": True,
        "json_serializer": _dumps,
    }
    if make_url(settings.db_url).get_backend_name() != "sqlite":
        engine_kwargs.update(
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_pre_ping=True,
        )

    engine = create_async_engine(settings.db_url, **engine_kwargs)
    _enable_sqlite_foreign_keys(engine)
    return engine


# 铁律3：启动时预初始化连接池
engine = _build_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每请求一个 session。"""
    async with SessionLocal() as session:
        yield session
