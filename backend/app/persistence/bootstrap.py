"""数据库初始化 + 僵尸会话清扫 + 演示账号种入。"""
from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config_store import DEFAULTS
from app.core.security import hash_password_async
from app.domain.session import SessionStatus
from app.persistence.db import SessionLocal, engine
from app.persistence.models import Base, InterviewRecord, User

logger = logging.getLogger(__name__)


# dev 自愈：现有表缺列时 ADD COLUMN。prod 走 Alembic，不需要这条。
_SELF_HEAL_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, ddl_type_with_default)
    ("reports", "transcript_signature", "VARCHAR(64) DEFAULT ''"),
    ("interviews", "first_batch_generated", "BOOLEAN DEFAULT 0"),
]


async def _column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = await conn.execute(text(
            "SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"
        ), {"t": table, "c": column})
    elif dialect == "mysql":
        result = await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
    elif dialect == "postgresql":
        result = await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
    else:
        logger.warning("dev 自愈跳过：未支持方言 %s", dialect)
        return True  # 视为存在，避免误 ALTER
    return result.scalar() is not None


async def _ensure_columns(conn: AsyncConnection) -> None:
    """dev 自愈：缺列就 ADD COLUMN；idempotent。"""
    for table, column, ddl in _SELF_HEAL_COLUMNS:
        if await _column_exists(conn, table, column):
            continue
        logger.info("dev 自愈：ALTER TABLE %s ADD COLUMN %s", table, column)
        await conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
        ))


async def init_db() -> None:
    """建表 + 缺列自愈 + 种入演示账号。lifespan 启动时调一次。

    dev（默认）：Base.metadata.create_all + 缺列自愈（本地快速启动）
    prod（APP_DB_USE_ALEMBIC=1）：走 alembic upgrade head（迁移式版本管理）
    """
    if os.environ.get("APP_DB_USE_ALEMBIC") == "1":
        backend_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=backend_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
            )
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_columns(conn)
    await seed_dev_users()


async def seed_dev_users() -> None:
    """开发演示账号种入（仅 admin；其他用户由集成测试动态创建）。

    注：直接读 DEFAULTS 而非 ConfigStore，因为 init_db 在 ConfigStore.warm() 之前调用。
    P2-7: 密码不再走 ConfigStore.demo_password——admin 默认密码在无 password env 时
    生成一次性随机口令并打到日志；prod 环境首启同样随机。改密走 /admin/auth/password。
    """
    from app.core.settings import get_settings

    settings = get_settings()
    username = DEFAULTS["auth.demo_username"]
    # password env 覆盖：dev/prod 都允许 APP_ADMIN_PASSWORD env 注入固定口令
    # 走 Settings（pydantic-settings 自动读 .env + 环境变量），而不是裸 os.environ.get
    password = settings.app_admin_password or ""
    if not username:
        return
    if not password:
        import secrets as _s

        password = _s.token_urlsafe(18)
        # 不打日志密码字面量（避免被收集到日志聚合系统泄露）；
        # 通过另一个 endpoint /admin/auth/password 改密时用户已登录能看到当前用户名。
        logger.warning(
            "首启：未设 APP_ADMIN_PASSWORD env，已为 admin 随机生成一次性密码。"
            "请通过 POST /admin/auth/password 修改。"
        )
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.username == username))
        row = existing.scalar_one_or_none()
        if row is None:
            session.add(User(
                id=str(uuid.uuid4()),
                username=username,
                password_hash=await hash_password_async(password),
                role="admin",
            ))
        elif row.role != "admin":
            row.role = "admin"
        await session.commit()


async def sweep_stale_sessions() -> int:
    """启动时把断连的进行中访谈转为已暂停（in_progress → suspended），可继续。

    重启后这些会话已无 live WS（连接随旧进程死了），但不强制结束——用户重启后
    仍应能重新进入继续访谈。优雅关闭时 shutdown_quick 已转 suspended；这里兜底
    强杀（kill -9 / Ctrl+C 两次）场景——那种情况下 shutdown_quick 没机会跑，
    DB 仍卡 in_progress。语义与存活窗口超时一致（manager._grace_expire）。
    不写 ended / ended_at。
    """
    async with SessionLocal() as session:
        res = await session.execute(
            select(InterviewRecord).where(
                InterviewRecord.status == SessionStatus.IN_PROGRESS.value,
            )
        )
        stale = list(res.scalars().all())
        for rec in stale:
            rec.status = SessionStatus.SUSPENDED.value
        if stale:
            await session.commit()
        return len(stale)
