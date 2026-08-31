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


# === P2 模板校验加强（#3 / #5 / #6 / #7 / #9） ===

def _minimal_template(**overrides) -> dict:
    """最小可构造的模板 dict；tests 用 overrides 触发各校验路径。"""
    base = {
        "id": "qa-tpl",
        "name": "QA 测试模板",
        "session": {
            "name": "s", "goal": "",
            "base_fields": [{"key": "project", "label": "项目"}],
            "setup": {"intro": "", "extract_to": [], "required": []},
        },
        "coaching": {"playbook": "", "must_ask": []},
        "report": {"doc": ""},
        "safety": [],
    }
    base.update(overrides)
    return base


def test_template_session_required():
    """#3 session 缺则 pydantic 直接 422，不再填空壳。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import Template

    data = _minimal_template()
    del data["session"]
    with pytest.raises(ValidationError) as exc:
        Template.model_validate(data)
    assert "session" in str(exc.value).lower()


def test_template_coaching_required():
    """#3 coaching 缺则 422。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import Template

    data = _minimal_template()
    del data["coaching"]
    with pytest.raises(ValidationError) as exc:
        Template.model_validate(data)
    assert "coaching" in str(exc.value).lower()


def test_template_report_required():
    """#3 report 缺则 422。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import Template

    data = _minimal_template()
    del data["report"]
    with pytest.raises(ValidationError) as exc:
        Template.model_validate(data)
    assert "report" in str(exc.value).lower()


def test_base_field_type_must_be_enum():
    """#5 type 仅允许 text/datetime/duration；非法值 422。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import BaseField

    BaseField(key="ok1", label="x", type="text")
    BaseField(key="ok2", label="x", type="datetime")
    BaseField(key="ok3", label="x", type="duration")
    BaseField(key="ok4", label="x")  # 默认 text

    with pytest.raises(ValidationError):
        BaseField(key="bad", label="x", type="number")
    with pytest.raises(ValidationError):
        BaseField(key="bad", label="x", type="select")


def test_base_field_key_pattern():
    """#6 key 必须是 ^[a-z][a-z0-9_]*$：空串 / 中文 / 大写 / 连字符开头 全拒。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import BaseField

    # 合法
    BaseField(key="project")
    BaseField(key="customer_name")
    BaseField(key="visit_time_2")

    # 非法
    with pytest.raises(ValidationError):
        BaseField(key="")  # 空串
    with pytest.raises(ValidationError):
        BaseField(key="Project")  # 大写
    with pytest.raises(ValidationError):
        BaseField(key="_internal")  # 下划线开头
    with pytest.raises(ValidationError):
        BaseField(key="中文键")  # 中文
    with pytest.raises(ValidationError):
        BaseField(key="customer-name")  # 连字符


def test_template_name_strips_whitespace():
    """#7 name 纯空格 trim 后判空——min_length=1 单独不够。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import Template

    data = _minimal_template(name="  qa 模板  ")
    tpl = Template.model_validate(data)
    assert tpl.name == "qa 模板"  # 内部空白保留，两端 strip

    data = _minimal_template(name="   ")
    with pytest.raises(ValidationError):
        Template.model_validate(data)


def test_template_extra_forbidden():
    """#9 extra=forbid：未知顶层字段直接 422，避免「mustAsk 错写 must_ask」之类静默丢数据。"""
    import pytest
    from pydantic import ValidationError

    from app.domain.template import Template

    data = _minimal_template()
    data["evil_extra"] = "boom"
    with pytest.raises(ValidationError):
        Template.model_validate(data)
