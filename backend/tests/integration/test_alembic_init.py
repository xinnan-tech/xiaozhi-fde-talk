"""· alembic 引入。

事实级硬伤：仓内 alembic 配置 0 处；唯一建表途径 Base.metadata.create_all 非幂等无版本管理。
P2-12/15/8c/P3-4 都强依赖 alembic。

验证：(a) alembic.ini 存在；(b) migrations/ 目录存在；(c) alembic upgrade head 成功；
(d) alembic downgrade base 成功；(e) 初始迁移 0001_* 存在。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_alembic(*args: str, db_url: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "APP_DB_USE_ALEMBIC": "1"}
    if db_url is not None:
        env["DATABASE_URL"] = db_url
    return subprocess.run(
        ["alembic", *args],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def test_alembic_ini_exists():
    assert (BACKEND_ROOT / "alembic.ini").exists(), "缺少 alembic.ini"


def test_migrations_dir_exists():
    assert (BACKEND_ROOT / "migrations" / "env.py").exists(), "缺少 migrations/env.py"
    assert (BACKEND_ROOT / "migrations" / "script.py.mako").exists(), "缺少 migrations/script.py.mako"


def test_initial_migration_exists():
    versions = list((BACKEND_ROOT / "migrations" / "versions").glob("*.py"))
    assert any(v.stem.startswith("0001_") for v in versions), \
        f"缺少 0001_*.py 初始迁移；现有: {[v.name for v in versions]}"


def test_alembic_upgrade_head_succeeds(tmp_path):
    """新 SQLite 库跑 alembic upgrade head 应成功建表。"""
    db_path = tmp_path / "alembic_test.db"
    result = _run_alembic("upgrade", "head", db_url=f"sqlite+aiosqlite:///{db_path}")
    assert result.returncode == 0, f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
    assert db_path.exists(), "DB 文件未创建"


def test_alembic_downgrade_base_succeeds(tmp_path):
    """alembic upgrade head 后 downgrade base 应成功（schema 清空）。"""
    db_path = tmp_path / "alembic_test_down.db"
    _run_alembic("upgrade", "head", db_url=f"sqlite+aiosqlite:///{db_path}")
    result = _run_alembic("downgrade", "base", db_url=f"sqlite+aiosqlite:///{db_path}")
    assert result.returncode == 0, f"alembic downgrade base 失败:\n{result.stdout}\n{result.stderr}"
