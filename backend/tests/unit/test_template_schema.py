"""模板表 ORM 结构 + 迁移 0002（DDL）+ seed 常量。"""
from __future__ import annotations

import sqlite3
import subprocess
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


def test_migration_0002_creates_tables(tmp_path, monkeypatch):
    """alembic upgrade head 在空库上建出 templates 表 + snapshot 列（prod 路径）。"""
    db = tmp_path / "mig.db"
    monkeypatch.setenv("DB_URL", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    from app.core.settings import get_settings
    get_settings.cache_clear()
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

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
