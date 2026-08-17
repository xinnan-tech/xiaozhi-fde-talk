"""datetime columns timezone aware

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-11

P3-4: 所有 DateTime 列改 timezone=True（interviews / reports / system_config /
users）。SQLite 用 batch_alter_table 重建表改列类型。存量值保持原样读回
（naive 行仍按 naive 读，应用层 bootstrap 已防御性处理 tz）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("interviews") as batch:
        batch.alter_column("created_at", type_=sa.DateTime(timezone=True))
        batch.alter_column("started_at", type_=sa.DateTime(timezone=True))
        batch.alter_column("ended_at", type_=sa.DateTime(timezone=True))
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("created_at", type_=sa.DateTime(timezone=True))
        batch.alter_column("updated_at", type_=sa.DateTime(timezone=True))
    with op.batch_alter_table("system_config") as batch:
        batch.alter_column("created_at", type_=sa.DateTime(timezone=True))
        batch.alter_column("updated_at", type_=sa.DateTime(timezone=True))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("created_at", type_=sa.DateTime(timezone=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("created_at", type_=sa.DateTime())
    with op.batch_alter_table("system_config") as batch:
        batch.alter_column("created_at", type_=sa.DateTime())
        batch.alter_column("updated_at", type_=sa.DateTime())
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("created_at", type_=sa.DateTime())
        batch.alter_column("updated_at", type_=sa.DateTime())
    with op.batch_alter_table("interviews") as batch:
        batch.alter_column("created_at", type_=sa.DateTime())
        batch.alter_column("started_at", type_=sa.DateTime())
        batch.alter_column("ended_at", type_=sa.DateTime())
