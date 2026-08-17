"""P2-6 · JWT 密钥首次持久化按方言选择原生 insert。

M8：_save_to_db 当前只用 sqlite_insert + on_conflict_do_nothing，在 PostgreSQL/MySQL
上编译直接抛错（PG AttributeError / MySQL UnsupportedCompilationError）—— prod 部署
首次落密钥即崩。

判定：用假 session（bind.dialect.name 可控）捕获 _save_to_db 交给 execute 的语句，
按对应方言编译：
- 当前代码无视方言恒用 sqlite_insert → mysql/pg 方言编译抛错（红）
- 修复后按方言选 mysql INSERT IGNORE / pg·sqlite ON CONFLICT DO NOTHING → 干净编译（绿）
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import mysql as mysql_dialect
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect

from app.core.secret import JWTSecretResolver


class _FakeSession:
    """假 async session：记录 execute 的语句，bind.dialect.name 可控。"""

    def __init__(self, dialect_name: str) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.captured = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.captured = stmt

    async def commit(self):
        pass


def _compile(stmt, dialect_name: str) -> str:
    dialect = {
        "sqlite": sqlite_dialect,
        "postgresql": pg_dialect,
        "mysql": mysql_dialect,
    }[dialect_name]
    return str(stmt.compile(
        dialect=dialect.dialect(), compile_kwargs={"literal_binds": True}
    ))


@pytest.mark.parametrize("dialect_name", ["sqlite", "postgresql", "mysql"])
@pytest.mark.asyncio
async def test_save_to_db_compiles_cleanly_per_dialect(dialect_name):
    sess = _FakeSession(dialect_name)
    resolver = JWTSecretResolver(settings=MagicMock(), session_factory=lambda: sess)

    # 不应抛——方言选错会让 compile 在下游崩
    await resolver._save_to_db("a-strong-secret-value")

    assert sess.captured is not None, "_save_to_db 未执行任何语句"
    sql = _compile(sess.captured, dialect_name).upper()

    if dialect_name == "mysql":
        assert "IGNORE" in sql and "ON CONFLICT" not in sql, (
            f"MySQL 应走 INSERT IGNORE，实际 SQL：{sql}"
        )
    else:  # sqlite / postgresql
        assert "ON CONFLICT" in sql, (
            f"{dialect_name} 应走 ON CONFLICT DO NOTHING，实际 SQL：{sql}"
        )
