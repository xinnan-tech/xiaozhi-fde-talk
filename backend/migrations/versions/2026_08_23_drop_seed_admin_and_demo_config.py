"""drop seed admin + demo_username; add password_changed_at

Revision ID: 2026_08_23_drop_seed_admin
Revises: 0008
Create Date: 2026-08-23

自助式用户体系：移除启动期硬配置 admin 演示账号。
- users 新增 password_changed_at 列（nullable）→ 改密即吊销旧 token
- 回填 password_changed_at = created_at（避免一刀切让现有 token 全部失效）
- 窄清 username='admin' AND role='admin' 的种子用户（不再需要）
- 删 system_config.auth.demo_username 配置项
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_08_23_drop_seed_admin"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 加列（先加列，后清理，避免删行时锁冲突）
    op.add_column("users", sa.Column(
        "password_changed_at",
        sa.DateTime(timezone=True),
        nullable=True,
    ))
    # 2. 回填旧行（按 created_at），避免一刀切让所有现有 token 失效
    op.execute(
        "UPDATE users SET password_changed_at = created_at "
        "WHERE password_changed_at IS NULL"
    )
    # 3. 窄清理种子 admin
    op.execute("DELETE FROM users WHERE username = 'admin' AND role = 'admin'")
    # 4. 删 demo_username 配置行
    op.execute("DELETE FROM system_config WHERE key = 'auth.demo_username'")


def downgrade() -> None:
    # 不可逆：删了的 admin 和 demo_username 不恢复
    op.drop_column("users", "password_changed_at")
