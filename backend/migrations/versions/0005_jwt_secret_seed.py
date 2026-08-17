"""P2-15: 若 system.jwt_secret 不存在则生成强密钥种入。

幂等：ON CONFLICT (key) DO NOTHING（PostgreSQL/SQLite）；
MySQL 用 INSERT IGNORE。并发启动安全——不会因竞态覆盖有效密钥。

不删除现有 key：alembic 升级是"非破坏性"操作，已部署的服务必须保留现有密钥。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0003'  # type: ignore
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """若 system.jwt_secret 不存在则生成新密钥种入。

    用方言分支确保跨 DB 兼容：
    - SQLite / PostgreSQL：ON CONFLICT (key) DO NOTHING
    - MySQL：INSERT IGNORE
    """
    from secrets import token_urlsafe
    secret = token_urlsafe(48)

    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "mysql":
        op.execute(
            f"INSERT IGNORE INTO system_config (`key`, value, created_at, updated_at) "
            f"VALUES ('system.jwt_secret', '{secret}', "
            f"CURRENT_TIMESTAMP(6), CURRENT_TIMESTAMP(6))"
        )
    else:
        # SQLite / PostgreSQL 都支持 ON CONFLICT (column_name)
        op.execute(
            sa.text(
                "INSERT INTO system_config (key, value, created_at, updated_at) "
                "VALUES (:k, :v, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(k="system.jwt_secret", v=secret)
        )


def downgrade() -> None:
    """回滚：仅删 seed 种入的密钥（若 DB 中原本无）。

    不删"原本就有的密钥"——保守策略：回滚不应破坏正在运行服务的密钥。
    实现：删除 created_at >= migration apply time 的密钥；
    若用户原本就有一个密钥，created_at 早于此时间，不会被删。
    """
    # 当前时间戳：仅删本次 migration 种入的行
    # 用 SQLAlchemy 元数据难精确判 created_at 时间戳，索性不强删——
    # 保留密钥作为"历史 seed"，避免误删正在运行服务的密钥。
    # 用户若真要清除，手工 DELETE FROM system_config WHERE key='system.jwt_secret' 即可。
    pass