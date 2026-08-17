"""report fk cascade + unique interview_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

P2-12: reports.interview_id 加外键 ondelete CASCADE（删访谈清报告）+ unique
（一次访谈一份报告）。原 0001 仅非唯一索引、无外键。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 外键 CASCADE：SQLite 需 batch_alter_table 重建表才能加约束
    with op.batch_alter_table("reports", schema=None) as batch:
        batch.create_foreign_key(
            "fk_reports_interview_id_interviews",
            "interviews",
            ["interview_id"],
            ["id"],
            ondelete="CASCADE",
        )
    # 旧非唯一索引 → 唯一索引
    op.drop_index(op.f("ix_reports_interview_id"), table_name="reports")
    op.create_index(
        op.f("ix_reports_interview_id"), "reports", ["interview_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_reports_interview_id"), table_name="reports")
    op.create_index(
        op.f("ix_reports_interview_id"), "reports", ["interview_id"], unique=False
    )
    with op.batch_alter_table("reports", schema=None) as batch:
        batch.drop_constraint("fk_reports_interview_id_interviews", type_="foreignkey")
