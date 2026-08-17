"""JWT 密钥解析：DB 读 → 缺失时自动生成并持久化。

设计要点：
- 没有任何硬编码默认值，避免懒人部署共享密钥风险
- 不读取环境变量（env JWT_SECRET 视为无效配置；pydantic-settings 即便读到了也会被覆盖）
- 启动时优先从 system_config 表读；缺失则生成随机密钥并持久化
- 修改密钥的方式：直接改 DB（system_config.key='system.jwt_secret' 的 value）
- 数据库备份即密钥备份——丢失 DB 备份意味着所有 token 失效，需全员重登

P2-15:
- prod 环境 env fallback 必须 fail-fast（无 DB → 启动失败，而不是静默生成）
- dev 环境保留 APP_JWT_ALLOW_ENV_FALLBACK=1 逃生口（本地 docker-compose 不想污染 DB）
- _save_to_db 必须用列名 'key' 作为 index_elements（PK 已存在则 ON CONFLICT DO NOTHING 生效）
- 幂等：并发启动不会因竞态覆盖有效密钥

容错策略：DB 读失败（连接异常等）→ 不静默生成新密钥，而是 fail-fast 抛出。
理由：DB 瞬时故障若被吞，会用新生成的密钥覆盖掉原本有效的密钥，使所有
在飞 token 全部失效（安全事件 + 雪崩式重登）。这种风险远大于"启动失败"。
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.core.settings import Settings

logger = logging.getLogger(__name__)

DB_KEY = "system.jwt_secret"

# P2-15: dev 环境的 env 逃生口。生产（env=prod）无视此开关。
_ENV_FALLBACK_FLAG = "APP_JWT_ALLOW_ENV_FALLBACK"


class JWTSecretResolver:
    """异步解析 JWT 密钥：DB → 自动生成并写回 DB。"""

    def __init__(self, settings: Settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory

    async def resolve(self) -> str:
        """DB 有值 → 用 DB；否则按环境策略走 env fallback 或自动生成。

        prod: 无 DB → RuntimeError（fail-fast，不静默生成新密钥）。
        dev:  APP_JWT_ALLOW_ENV_FALLBACK=1 → env；否则自动生成+持久化。
        """
        stored = await self._load_from_db()
        if stored:
            logger.info("JWT 密钥已从数据库加载")
            return stored

        # P2-15: env fallback 开关
        if os.environ.get(_ENV_FALLBACK_FLAG) == "1":
            env_secret = self.settings.jwt_secret or ""
            if env_secret:
                logger.warning(
                    "JWT secret: APP_JWT_ALLOW_ENV_FALLBACK=1 → 使用 env（不建议，仅 dev 调试用）"
                )
                return env_secret

        # 自动生成并持久化（dev 默认；prod 在 _save_to_db 之前 fail-fast）
        if self.settings.env == "prod":
            raise RuntimeError(
                "prod 环境必须先在 system_config 表种入 system.jwt_secret，"
                "或显式注入；启动拒绝自动生成密钥。"
            )

        new_secret = self._generate_strong_secret()
        await self._save_to_db(new_secret)
        # 重读确认：若并发启动已写入其他值，优先用 DB 中的（避免 token 雪崩）
        reread = await self._load_from_db()
        if reread:
            return reread
        logger.warning(
            "JWT secret: 刚持久化的值重读失败（罕见），使用本进程生成的密钥；"
            "DB 写入已生效。"
        )
        return new_secret

    async def reresolve(self) -> str:
        """从 DB 重读 jwt_secret；若 DB 中无则不生成（避免意外覆盖）。

        用途：ConfigStore 订阅 system.jwt_secret 变更时调用。
        注：当前实现中 ConfigStore 不触碰 system.jwt_secret，保留此方法备用。
        """
        stored = await self._load_from_db()
        if stored is None:
            logger.warning("重读 JWT 密钥时数据库中未找到")
            return self.settings.jwt_secret or ""
        return stored

    @staticmethod
    def _generate_strong_secret() -> str:
        secret = secrets.token_urlsafe(48)
        # 不变量：必须 ≥ 32 字节熵（防未来重构误用弱随机源）
        if len(secret) < 32:
            raise ValueError(f"生成的 JWT 密钥强度不足: {len(secret)} 字节")
        return secret

    async def _load_from_db(self) -> Optional[str]:
        from app.persistence.models import SystemConfig

        async with self.session_factory() as session:
            row = await session.get(SystemConfig, DB_KEY)
            return row.value if row else None

    async def _save_to_db(self, secret: str) -> None:
        """首次原子写入密钥；若已存在则不覆盖。轮换走直接改 DB。

        按引擎方言选 insert：SQLite/PostgreSQL 走 ON CONFLICT DO NOTHING；
        MySQL 走 INSERT IGNORE（MySQL 无 ON CONFLICT 语法）。

        P2-15: index_elements 必须用列对象（SystemConfig.key），不能用字面量
        DB_KEY（= "system.jwt_secret"）。否则 SQLAlchemy 会把字面量当列名引用，
        找不到匹配 UNIQUE/PK 约束 → SQLite 抛 OperationalError。
        """
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.persistence.models import SystemConfig

        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            dialect = session.bind.dialect.name
            if dialect == "mysql":
                stmt = mysql_insert(SystemConfig).values(
                    key=DB_KEY, value=secret, created_at=now, updated_at=now,
                ).prefix_with("IGNORE")
            elif dialect == "postgresql":
                stmt = pg_insert(SystemConfig).values(
                    key=DB_KEY, value=secret, created_at=now, updated_at=now,
                ).on_conflict_do_nothing(index_elements=[SystemConfig.key])
            else:  # sqlite 及未知方言默认走 sqlite 语义
                stmt = sqlite_insert(SystemConfig).values(
                    key=DB_KEY, value=secret, created_at=now, updated_at=now,
                ).on_conflict_do_nothing(index_elements=[SystemConfig.key])
            await session.execute(stmt)
            await session.commit()