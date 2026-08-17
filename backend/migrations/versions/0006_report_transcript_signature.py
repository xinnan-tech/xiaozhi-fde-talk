"""reports.transcript_signature 列

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15

报告缓存指纹（sha256[:16]，transcript 变则报告重生成）。列此前只在 ORM 模型
与 dev 缺列自愈里存在，走 Alembic 的部署缺这列会让报告读写直接 OperationalError。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("transcript_signature", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("reports", schema=None) as batch:
        batch.drop_column("transcript_signature")
