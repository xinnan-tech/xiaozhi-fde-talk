"""模板表 ORM 结构 + 迁移 0009（DDL）+ seed 常量。"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_template_record_columns():
    """TemplateRecord 声明了全部预期列（content JSON 为真相源 + 冗余展示列）。"""
    from app.persistence.models import TemplateRecord

    cols = {c.name for c in TemplateRecord.__table__.columns}
    assert {
        "id", "name", "icon_url", "icon_alt", "version",
        "content", "created_at", "updated_at",
    } == cols


def test_interview_record_has_snapshot():
    from app.persistence.models import InterviewRecord

    cols = {c.name for c in InterviewRecord.__table__.columns}
    assert "template_snapshot" in cols


def test_seed_contains_pm_template():
    from app.services.template.seed import SEED_TEMPLATES

    pm = [t for t in SEED_TEMPLATES if t["id"] == "pm-research"]
    assert len(pm) == 1
    assert pm[0]["name"] == "产品经理"
    assert pm[0]["coaching"]["must_ask"][0]["id"] == "objective"


def test_migration_0009_creates_tables(tmp_path, monkeypatch):
    """0009 迁移自身 DDL：templates 表 + snapshot 列。

    本分支 collapse 了 0001（main 的 0002~0008 + 2026_08_23_* 全折回 0001），
    0009 的 down_revision 指向 2026_08_23_drop_seed_admin（main head），本分支
    没有该文件——alembic upgrade head 走不通，连 alembic upgrade 0001 也会因
    revision_map 解析失败拒绝加载。改走：手工建出 0009 依赖的「前置 interviews
    表」（不带 snapshot 列），再直接调 0009 的 upgrade() 验证其 DDL。prod 合并
    后链完整与否由合并方负责。
    """
    db = tmp_path / "mig.db"
    monkeypatch.setenv("DB_URL", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    from app.core.settings import get_settings
    from sqlalchemy import create_engine
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    get_settings.cache_clear()
    try:
        # 1) 手工建出 0009 依赖的「前置 interviews 表」——不带 snapshot 列
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE interviews (id VARCHAR(36) PRIMARY KEY)"
            )

        # 2) 直接调 0009 的 upgrade() 验证其 DDL
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            import alembic.op as alembic_op
            alembic_op._proxy = ops  # type: ignore[attr-defined]
            migration = importlib.import_module(
                "migrations.versions.0009_templates_to_db"
            )
            migration.upgrade()
        con = sqlite3.connect(db)
        try:
            tables = {
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "templates" in tables
            cols = {r[1] for r in con.execute("PRAGMA table_info(interviews)")}
            assert "template_snapshot" in cols
        finally:
            con.close()
    finally:
        # monkeypatch 只还原 env 不还原 lru_cache——不清会让后续测试
        # 连到已消失的 tmp 库
        get_settings.cache_clear()
