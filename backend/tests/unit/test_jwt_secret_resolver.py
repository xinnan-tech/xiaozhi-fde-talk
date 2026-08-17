"""JWT 密钥解析器：DB 读 → 缺失时自动生成并持久化。

设计：完全不再读环境变量、不再有硬编码默认值，简化到只剩 DB → generate-and-persist。
容错：DB 读异常时 fail-fast，绝不静默生成新密钥覆盖有效密钥。
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.secret import DB_KEY, JWTSecretResolver
from app.core.settings import Settings
from app.persistence.models import SystemConfig

# 真实 AsyncSession 暴露 .bind（引擎）；_save_to_db 据此判方言。假 session 同步提供。
_SQLITE_BIND = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


class FakeSession:
    """模拟 AsyncSession for SystemConfig 查询。"""

    bind = _SQLITE_BIND

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, model, key):
        return None

    async def execute(self, stmt):
        pass

    async def commit(self):
        pass

    async def merge(self, obj):
        pass


def test_resolve_loads_from_db_when_present():
    """DB 有值 → 直接从 DB 加载（无视 env 是否有值）。"""
    settings = Settings(jwt_secret="env-should-be-ignored-here", env="dev")
    fake = FakeSession()
    fake.get = AsyncMock(
        return_value=SystemConfig(
            key=DB_KEY,
            value="db-stored-32-byte-secret-xxx",
            created_at=datetime.now(timezone.utc),
        )
    )
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)
    assert asyncio.run(resolver.resolve()) == "db-stored-32-byte-secret-xxx"


def test_resolve_generates_and_persists_when_db_empty():
    """DB 没值 → 生成随机密钥（≥32 字节）+ 原子 INSERT 持久化 + 重读返回该值。"""
    settings = Settings(jwt_secret=None, env="dev")
    generated = "generated-strong-secret-32-bytes-xxx"

    class ReflectingSession:
        """get 反映最近一次 INSERT 写入的 value，模拟 resolve 重读行为。"""

        def __init__(self):
            self.stored = None
            self.executed = []
            self.bind = _SQLITE_BIND

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, model, key):
            if self.stored is None:
                return None
            return SystemConfig(
                key=DB_KEY,
                value=self.stored,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        async def execute(self, stmt):
            self.executed.append(stmt)
            self.stored = generated

        async def commit(self):
            pass

    fake = ReflectingSession()
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)
    resolver._generate_strong_secret = lambda: generated

    secret = asyncio.run(resolver.resolve())

    assert secret == generated
    assert len(secret) >= 32
    assert len(fake.executed) == 1
    sql = str(fake.executed[0]).lower()
    assert "insert" in sql and "conflict" in sql


def test_resolve_propagates_db_lookup_failure():
    """DB 查询异常 → 抛错（fail-fast；绝不能静默生成新密钥覆盖有效密钥）。"""
    settings = Settings(jwt_secret=None, env="dev")
    fake = FakeSession()

    async def _raise(*args, **kwargs):
        raise RuntimeError("db down")

    fake.get = _raise
    fake.merge = AsyncMock()
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    with pytest.raises(RuntimeError, match="db down"):
        asyncio.run(resolver.resolve())

    # 关键断言：merge 没被调用——绝不能用新密钥覆盖有效密钥
    fake.merge.assert_not_called()


def test_save_to_db_is_atomic_insert_no_merge():
    """_save_to_db 走原子 INSERT，不再 select-then-merge（避免 TOCTOU）。"""
    settings = Settings(jwt_secret=None, env="dev")
    fake = FakeSession()
    fake.execute = AsyncMock()
    fake.merge = AsyncMock()
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    asyncio.run(resolver._save_to_db("new-secret-32-bytes-padding-xxx"))

    fake.merge.assert_not_called()
    fake.execute.assert_called_once()


def test_reresolve_loads_from_db_when_present():
    """DB 有 secret X，settings 有 secret Y（旧的）→ reresolve 返回 X。"""
    settings = Settings(jwt_secret="settings-stale-value", env="dev")
    fake = FakeSession()
    fake.get = AsyncMock(
        return_value=SystemConfig(
            key=DB_KEY,
            value="db-fresh-32-byte-secret-xxx",
            created_at=datetime.now(timezone.utc),
        )
    )
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)
    assert asyncio.run(resolver.reresolve()) == "db-fresh-32-byte-secret-xxx"


def test_reresolve_returns_settings_when_db_empty():
    """DB 无 secret → 不生成，fallback 返回 settings 当前值（不覆盖）。"""
    settings = Settings(jwt_secret="settings-fallback-32-byte-secret", env="dev")
    fake = FakeSession()
    fake.get = AsyncMock(return_value=None)
    fake.merge = AsyncMock()
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    result = asyncio.run(resolver.reresolve())

    assert result == "settings-fallback-32-byte-secret"
    fake.merge.assert_not_called()  # 关键：绝不能因为 reresolve 而写入