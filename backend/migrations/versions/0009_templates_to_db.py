"""templates 表 + interviews.template_snapshot 快照列

Revision ID: 0009
Revises: 0001
Create Date: 2026-08-29

纯 DDL。种子（pm-research 模板内容）在代码 app/services/template/seed.py，
由 loader.warm() 空表时幂等种入——dev/test 走 create_all 不经过本迁移，
种子放这里会漏掉 dev 库。

down_revision 必须挂在合并时 main 的 head 上，否则会分叉出第二个 head，
`alembic upgrade head`（bootstrap 启动路径）因 multiple heads 拒绝执行。
main 在 #112「collapse migrations」后已把 0002~0008 与
2026_08_23_drop_seed_admin_and_demo_config 全部折进 0001_initial.py 并删除，
所以当前 main 的唯一 head 就是 0001——本文件挂 0001 即单链，
`alembic heads` 只输出 0009 (head)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009"
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
