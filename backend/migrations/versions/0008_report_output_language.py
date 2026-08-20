"""reports.output_language 列

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19

报告缓存按语种失效维度。生成报告时记入当时的 llm.output_language（zh_cn /
zh_tw / en），下次 GET 比较：缓存行语种与当前不一致 → 视为失效，强制重生；
旧行此列为空 → 同样视为未标，定失效。

配合 backend/app/services/reports/generator.py 的 _cache_hit 与
output_language 透传使用；dev 自愈路径在 bootstrap._SELF_HEAL_COLUMNS。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("output_language", sa.String(16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("reports", schema=None) as batch:
        batch.drop_column("output_language")
