"""initial schema (complete current state)

Revision ID: 0001
Revises:
Create Date: 2026-08-11 09:58:41.398457

完整当前 schema。所有列/约束/类型在首次部署前已确定——历史演进已折回本文件。
迁移目录不再保留补丁迁移（FK CASCADE / UNIQUE / tz-aware DateTime /
transcript_signature / output_language / first_batch_generated /
password_changed_at 等一律内联）。

JWT secret 不在本迁移里种——见 app.persistence.bootstrap.init_db。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'interviews',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=64), nullable=False),
        sa.Column('template_version', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('base_info', sa.JSON(), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('transcript', sa.JSON(), nullable=False),
        sa.Column('coaching_items', sa.JSON(), nullable=False),
        sa.Column('skipped_ids', sa.JSON(), nullable=False),
        sa.Column('ignored_ids', sa.JSON(), nullable=False),
        sa.Column('coverage_index', sa.JSON(), nullable=False),
        sa.Column('consumed_seq', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        # 首评（LLM 定制第一批问题）是否已生成
        sa.Column('first_batch_generated', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_interviews_status'), 'interviews', ['status'], unique=False)
    op.create_index(op.f('ix_interviews_template_id'), 'interviews', ['template_id'], unique=False)
    op.create_index(op.f('ix_interviews_user_id'), 'interviews', ['user_id'], unique=False)

    op.create_table(
        'reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        # 一次访谈一份报告；删访谈 → 报告级联清掉
        sa.Column('interview_id', sa.String(length=36), nullable=False),
        sa.Column('content_md', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('skill_outputs', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        # transcript 指纹（sha256[:16]）；transcript 变 → 缓存失效、重生
        sa.Column('transcript_signature', sa.String(length=64), nullable=False,
                  server_default=''),
        # 生成时的 llm.output_language（zh_cn/zh_tw/en）；语种变 → 缓存失效、重生
        sa.Column('output_language', sa.String(length=16), nullable=False,
                  server_default=''),
        sa.ForeignKeyConstraint(
            ['interview_id'], ['interviews.id'],
            name='fk_reports_interview_id_interviews',
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint('interview_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    # 注：UniqueConstraint(interview_id) 已隐式创建唯一索引，无需再显式
    # op.create_index(..., unique=True)——否则会产生两个唯一索引（一个 sqlite
    # autoindex，一个 ix_reports_interview_id），schema-diff 工具困惑。

    op.create_table(
        'system_config',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        # 改密时间戳：JWT pwd_ver claim 比对此值实现即时吊销；nullable
        sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('system_config')
    # 注：reports.interview_id 的唯一性来自 UniqueConstraint（SQLite 隐式
    # sqlite_autoindex_reports_2），随 drop_table 自动消失，无需单独 drop_index。
    op.drop_table('reports')
    op.drop_index(op.f('ix_interviews_user_id'), table_name='interviews')
    op.drop_index(op.f('ix_interviews_template_id'), table_name='interviews')
    op.drop_index(op.f('ix_interviews_status'), table_name='interviews')
    op.drop_table('interviews')
