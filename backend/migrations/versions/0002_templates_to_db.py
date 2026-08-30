"""templates 表 + interviews.template_snapshot 快照列

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29

纯 DDL。种子（pm-research 模板内容）在代码 app/services/template/seed.py，
由 loader.warm() 空表时幂等种入——dev/test 走 create_all 不经过本迁移，
种子放这里会漏掉 dev 库。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("icon_url", sa.String(length=512), nullable=False),
        sa.Column("icon_alt", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "interviews",
        sa.Column("template_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interviews", "template_snapshot")
    op.drop_table("templates")
