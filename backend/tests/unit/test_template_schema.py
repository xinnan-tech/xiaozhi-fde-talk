"""模板表 ORM 结构 + 迁移 0002（DDL）+ seed 常量。"""
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


def test_base_field_default_and_placeholder():
    """BaseField 支持可选 default / placeholder：空串=未配置；列宽与 label 对齐。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import BaseField

    bare = BaseField(key="project", label="项目")
    assert bare.default == ""
    assert bare.placeholder == ""

    filled = BaseField(
        key="project", label="项目",
        default="售前", placeholder="如：智慧园区项目",
    )
    assert filled.default == "售前"
    assert filled.placeholder == "如：智慧园区项目"

    with pytest.raises(ValidationError):
        BaseField(key="p", label="项目", placeholder="x" * 129)
    with pytest.raises(ValidationError):
        BaseField(key="p", label="项目", default="x" * 129)


def test_session_title_goal_defaults():
    """访谈名称/访谈目标是固定伪字段：默认值挂 SessionBlock，空串=未配置。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import SessionBlock

    bare = SessionBlock()
    assert bare.title_default == ""
    assert bare.goal_default == ""

    filled = SessionBlock(
        title_default="企业官网改版需求调研",
        goal_default="搞清楚核心诉求与拍板人",
    )
    assert filled.title_default == "企业官网改版需求调研"
    assert filled.goal_default == "搞清楚核心诉求与拍板人"

    with pytest.raises(ValidationError):
        SessionBlock(title_default="x" * 129)
    with pytest.raises(ValidationError):
        SessionBlock(goal_default="x" * 129)


def test_seed_contains_pm_template():
    from app.services.template.seed import SEED_TEMPLATES

    pm = [t for t in SEED_TEMPLATES if t["id"] == "pm-research"]
    assert len(pm) == 1
    assert pm[0]["name"] == "产品经理"
    assert pm[0]["coaching"]["must_ask"][0]["id"] == "objective"

    # 行业通用演示：文本字段配默认值（预填）+ 占位提示；访谈名称/访谈目标
    # 是固定伪字段，默认值在 session.title_default / goal_default；
    # start_time/duration 由建访谈对话框自动兜底（此刻/45），不预置默认值
    session = pm[0]["session"]
    fields = {f["key"]: f for f in session["base_fields"]}
    assert session["title_default"] == "企业官网改版需求调研"
    assert session["goal_default"] == "搞清楚对方对官网改版的核心诉求、现有痛点和拍板人"
    assert fields["project"]["default"] == "企业官网改版"
    assert fields["interviewee"]["default"] == "客户方产品负责人"
    assert fields["project"].get("placeholder", "").startswith("如：")
    assert fields["interviewee"].get("placeholder", "").startswith("如：")
    assert all(
        not f.get("default") for f in session["base_fields"]
        if f["key"] not in ("project", "interviewee")
    )


def test_migration_0002_creates_tables(tmp_path, monkeypatch):
    """0002 迁移自身 DDL：templates 表 + snapshot 列。

    不走 alembic upgrade 跑全链（0001 的完整 schema 与本测试无关），
    改走：手工建出 0002 依赖的「前置 interviews 表」（不带 snapshot 列），
    再直接调 0002 的 upgrade() 验证其 DDL。
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
        # 1) 手工建出 0002 依赖的「前置 interviews 表」——不带 snapshot 列
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE interviews (id VARCHAR(36) PRIMARY KEY)"
            )

        # 2) 直接调 0002 的 upgrade() 验证其 DDL
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            import alembic.op as alembic_op
            alembic_op._proxy = ops  # type: ignore[attr-defined]
            migration = importlib.import_module(
                "migrations.versions.0002_templates_to_db"
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
