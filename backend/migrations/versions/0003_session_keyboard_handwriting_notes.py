"""手写 / 键盘笔记 + 画板 state —— session_keyboard_text / handwriting_images / interviews 镜像列。

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22

笔记真相源表:
- session_keyboard_text: 复合 PK (session_id, user_id) UPSERT 覆盖。
- handwriting_images: id 自增 PK,append + (user_id, image_hash) 联合唯一索引防连点/重试。
  canvas_index / canvas_payload / canvas_payload_hash 三个可空字段存画板
  state(笔触 / 状态 JSON,前端自增键 canvas_index 标识画板号 1/2/3)。

interviews 镜像列(冷启动恢复 runtime state):
- keyboard_text / handwriting_notes: notes 字段分组的 JSON 镜像。
- 0004 合并进来——画板 state 复用 handwriting_images,不进镜像列。

dev 自愈白名单同步更新(_SELF_HEAL_COLUMNS)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- interviews 镜像列(冷启动恢复 runtime state) ----
    op.add_column(
        "interviews",
        sa.Column("keyboard_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column(
            "handwriting_notes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    # ---- 键盘笔记真相源表 ----
    op.create_table(
        "session_keyboard_text",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interviews.id"],
            name="ck_session_keyboard_text_session_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="ck_session_keyboard_text_user_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", "user_id"),
    )

    # ---- 手写笔记 + 画板 state 表 ----
    op.create_table(
        "handwriting_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("image_base64", sa.Text(), nullable=False),
        sa.Column("image_format", sa.String(length=8), nullable=False),
        sa.Column("image_bytes_size", sa.Integer(), nullable=False),
        sa.Column(
            "ocr_status", sa.String(length=16),
            nullable=False, server_default="pending",
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("injected_at", sa.DateTime(timezone=True), nullable=True),
        # 画板 state(笔触 / 状态 JSON,服务器不解析字段内容)
        sa.Column("canvas_index", sa.Integer(), nullable=True),
        sa.Column("canvas_payload", sa.JSON(), nullable=True),
        sa.Column("canvas_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interviews.id"],
            name="ck_handwriting_images_session_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="ck_handwriting_images_user_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "image_hash", name="uq_handwriting_user_hash"),
        # 同一 session+user 下 canvas_index 唯一(可空 → 多行 NULL 允许)
        sa.UniqueConstraint(
            "session_id", "user_id", "canvas_index",
            name="uq_handwriting_canvas_index",
        ),
    )
    op.create_index(
        "ix_handwriting_images_session_id",
        "handwriting_images",
        ["session_id"],
    )
    op.create_index(
        "ix_handwriting_images_user_id",
        "handwriting_images",
        ["user_id"],
    )
    op.create_index(
        "ix_handwriting_canvas_index",
        "handwriting_images",
        ["canvas_index"],
    )
    op.create_index(
        "ix_handwriting_session_created",
        "handwriting_images",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_handwriting_session_created", table_name="handwriting_images")
    op.drop_index("ix_handwriting_canvas_index", table_name="handwriting_images")
    op.drop_index("ix_handwriting_images_user_id", table_name="handwriting_images")
    op.drop_index("ix_handwriting_images_session_id", table_name="handwriting_images")
    op.drop_table("handwriting_images")
    op.drop_table("session_keyboard_text")
    op.drop_column("interviews", "handwriting_notes")
    op.drop_column("interviews", "keyboard_text")