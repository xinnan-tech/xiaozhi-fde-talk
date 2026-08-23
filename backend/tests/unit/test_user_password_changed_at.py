"""User.password_changed_at 列存在性与可空性。

回归需求：改密吊销（JWT pwd_ver claim）依赖此列；dev 自愈清单 + Alembic 迁移
两侧都得加列，列被误删会造成所有用户登录后立刻 401。
"""
from app.persistence.models import User


def test_user_password_changed_at_column_exists():
    """User 表必须包含 password_changed_at 列，且默认为 None."""
    cols = {c.name for c in User.__table__.columns}
    assert "password_changed_at" in cols
    col = User.__table__.columns["password_changed_at"]
    assert col.nullable is True
