"""数据库初始化 + 僵尸会话清扫。"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.session import SessionStatus
from app.persistence.db import SessionLocal, engine
from app.persistence.models import Base, InterviewRecord

logger = logging.getLogger(__name__)


# dev 自愈：现有表缺列时 ADD COLUMN。prod 走 Alembic，不需要这条。
_SELF_HEAL_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, ddl_type_with_default)
    # 注：用 DATETIME 而非 TIMESTAMP —— SQLite 不识别 TIMESTAMP，dev 模式（未跑 alembic）直接报 unrecognized type。
    # DATETIME 在 MySQL/PG/SQLite 三方言下都有效，可空，无默认值。
    ("reports", "transcript_signature", "VARCHAR(64) DEFAULT ''"),
    ("reports", "output_language", "VARCHAR(16) DEFAULT ''"),
    ("interviews", "first_batch_generated", "BOOLEAN DEFAULT 0"),
    ("users", "password_changed_at", "DATETIME"),
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
    """建表 + 缺列自愈。lifespan 启动时调一次。

    dev/test（默认）：Base.metadata.create_all + 缺列自愈（本地快速启动）
    prod：强制 APP_DB_USE_ALEMBIC=1，走 alembic upgrade head——保留迁移历史，
    避免 create_all 漏迁移 / 自愈忘了落迁移文件导致下次 prod 升级撞 schema drift。
    """
    env = os.environ.get("APP_ENV", "dev")
    if env == "prod" or os.environ.get("APP_DB_USE_ALEMBIC") == "1":
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
