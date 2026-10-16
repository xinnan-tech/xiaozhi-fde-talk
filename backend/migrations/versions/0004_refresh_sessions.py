"""refresh_sessions 表：refresh token 会话登记簿

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

refresh token rotation / reuse 检测 / 撤销的事实源。撤销状态此前存进程
内存（token.py _revoked_refresh_jtis），重启清零、多 worker 互不可见——
本表落 DB 后 rotation 语义才成立。dev/test 走 create_all 自动建表；
存量部署升级时旧 refresh token 无行，按 legacy valid 处理（首见补登记）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_sessions",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        # server_default 同 0003 惯例：绕开 ORM 的 raw INSERT 忘填 status
        # 时落 active，而非 NOT NULL 500。
        sa.Column(
            "status", sa.String(length=16), nullable=False,
            server_default="active",
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint(
            "status IN ('active', 'rotated', 'revoked')",
            name="ck_refresh_sessions_status",
        ),
    )
    op.create_index(
        op.f("ix_refresh_sessions_user_id"),
        "refresh_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions"
    )
    op.drop_table("refresh_sessions")
