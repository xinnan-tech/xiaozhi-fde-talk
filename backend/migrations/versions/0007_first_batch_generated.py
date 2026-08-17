"""interviews.first_batch_generated：首评（LLM 定制第一批问题）是否已生成

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("interviews") as batch:
        batch.add_column(
            sa.Column("first_batch_generated", sa.Boolean(), nullable=False,
                      server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("interviews") as batch:
        batch.drop_column("first_batch_generated")
