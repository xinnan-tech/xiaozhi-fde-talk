"""· m-005 JWT fallback 移除 + 启动 fail-fast。

旧行为：resolve() 无视 env，DB 无值就直接生成+持久化。
- 缺幂等性保护（并发启动可生成多份 → token 全部失效）
- DB schema 上没有 UNIQUE 约束让 ON CONFLICT (key) 报错
- prod 环境无 secret 应该是 fail-fast，而不是静默生成

新行为：
1. 移除所有 env 兜底（APP_JWT_ALLOW_ENV_FALLBACK 开关用于 dev/local）
2. prod 环境 env 无 secret + DB 无 secret → RuntimeError（fail-fast）
3. dev 环境 env 无 secret + DB 无 secret → 自动生成 + 幂等 INSERT（ON CONFLICT DO NOTHING）
4. _save_to_db 必须用列名 "key" 作为 index_elements，不能用字面 value
"""
import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys
from app.core.secret import DB_KEY, JWTSecretResolver
from app.core.settings import Settings
from app.persistence.models import SystemConfig

_SQLITE_BIND = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


# ─────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────


class _FakeSessionBase:
    """最小可工作的 fake AsyncSession。"""
    bind = _SQLITE_BIND

    def __init__(self):
        self.stored: SystemConfig | None = None
        self.executed: list = []
        self.get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, model, key):
        self.get_calls += 1
        return self.stored

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def commit(self):
        pass


def _settings(env: str = "dev", secret: str | None = None) -> Settings:
    # prod 必须配 MySQL/PG URL（settings 校验）；测试用 postgresql 占位即可
    db_url = "postgresql+asyncpg://test/test" if env == "prod" else "sqlite+aiosqlite:///./x.db"
    return Settings(jwt_secret=secret, env=env, db_url=db_url)


# ─────────────────────────────────────────────────────────────────────
# tests
# ─────────────────────────────────────────────────────────────────────


def test_resolve_no_env_fallback_in_prod(monkeypatch):
    """prod: env 无 secret + DB 无 secret → I18nError(SECRET_RESOLVE_FAILED)（不静默生成）。

    关掉 APP_JWT_ALLOW_ENV_FALLBACK 兜底（默认关闭）。
    """
    monkeypatch.delenv("APP_JWT_ALLOW_ENV_FALLBACK", raising=False)
    settings = _settings(env="prod", secret=None)
    fake = _FakeSessionBase()  # stored=None → DB 读不到
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    with pytest.raises(I18nError) as ei:
        asyncio.run(resolver.resolve())
    assert ei.value.code == Keys.SECRET_RESOLVE_FAILED.value
    assert ei.value.http_status == 503

    # 关键不变量：prod 绝不能写入新密钥覆盖/生成
    assert len(fake.executed) == 0


def test_resolve_dev_first_boot_generates_and_persists_idempotently(monkeypatch):
    """dev: env 无 secret + DB 无 secret → 生成 + 持久化 + 重读返回。

    ON CONFLICT DO NOTHING 保证并发启动不会重复写入。
    """
    monkeypatch.delenv("APP_JWT_ALLOW_ENV_FALLBACK", raising=False)
    settings = _settings(env="dev", secret=None)
    fake = _FakeSessionBase()
    fake.execute = AsyncMock(side_effect=lambda stmt: _record_insert(fake, stmt))
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)
    generated = "dev-first-boot-32-bytes-strong-secret"
    resolver._generate_strong_secret = lambda: generated

    result = asyncio.run(resolver.resolve())

    assert result == generated
    assert len(result) >= 32
    fake.execute.assert_awaited()  # 至少调用一次 INSERT
    sql = str(fake.execute.await_args[0][0]).lower()
    assert "insert" in sql and "conflict" in sql  # 必须 ON CONFLICT DO NOTHING


def _record_insert(fake, stmt):
    """模拟 INSERT 成功后 fake.stored 立即可被 get 读到。"""
    fake.executed.append(stmt)
    # 推断写入的 value：从 stmt 的 compiled params
    params = getattr(stmt, "_params", None) or {}
    if params and "value" in params:
        fake.stored = SystemConfig(
            key=DB_KEY,
            value=params["value"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


def test_resolve_dev_env_fallback_switch(monkeypatch):
    """dev: APP_JWT_ALLOW_ENV_FALLBACK=1 → 走 env，不再生成新密钥。

    保留逃生口：本地 docker-compose 可用 env 注入而不污染 DB。
    """
    monkeypatch.setenv("APP_JWT_ALLOW_ENV_FALLBACK", "1")
    settings = _settings(env="dev", secret="dev-env-secret-32-bytes-padding")
    fake = _FakeSessionBase()  # DB 无值
    fake.execute = AsyncMock()  # 断言：未被调用
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    result = asyncio.run(resolver.resolve())

    assert result == "dev-env-secret-32-bytes-padding"
    fake.execute.assert_not_called()  # 不应走 INSERT


def test_resolve_uses_existing_db_value_over_env(monkeypatch):
    """DB 有值 → 用 DB；无视 env 是否设了 APP_JWT_ALLOW_ENV_FALLBACK。

    关键：DB 一旦写过 secret X，所有启动（包括 dev fallback 模式）都必须用 X，
    否则新签的 token 全部失效。
    """
    monkeypatch.setenv("APP_JWT_ALLOW_ENV_FALLBACK", "1")
    settings = _settings(env="dev", secret="env-should-be-ignored-here")
    fake = _FakeSessionBase()
    fake.stored = SystemConfig(
        key=DB_KEY,
        value="db-fresh-32-byte-secret-xxx",
        created_at=datetime.now(timezone.utc),
    )
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    assert asyncio.run(resolver.resolve()) == "db-fresh-32-byte-secret-xxx"


def test_save_to_db_uses_column_name_not_value(monkeypatch):
    """_save_to_db 必须用列名 'key' 作为 index_elements（不是 value 字面量）。

    Bug 复现：旧实现 index_elements=[DB_KEY]（即 ["system.jwt_secret"]），
    SQLAlchemy 把它当列名引用，加引号后是 "system.jwt_secret" —— 但实际列是 key，
    找不到匹配 UNIQUE/PK 约束 → SQLite 抛 OperationalError。
    """
    monkeypatch.delenv("APP_JWT_ALLOW_ENV_FALLBACK", raising=False)
    settings = _settings(env="dev", secret=None)
    fake = _FakeSessionBase()
    fake.execute = AsyncMock()
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    asyncio.run(resolver._save_to_db("new-secret-32-bytes-padding-xxx"))

    fake.execute.assert_awaited_once()
    stmt = fake.execute.await_args[0][0]
    sql = str(stmt).lower()
    # 必须用真正的列名 "key"（不带点）
    assert '"key"' in sql or "'key'" in sql or "key " in sql
    # 不应是字面 value "system.jwt_secret"
    assert '"system.jwt_secret"' not in sql


def test_resolve_prod_failure_does_not_leak_secret(monkeypatch):
    """T14 step 4: prod 启动失败的 I18nError 渲染文本不能含 DB/env 密钥。

    回归保护：避免有人在 future 重构中把 secret 值塞进 params 让 admin UI 暴露它。
    """
    monkeypatch.delenv("APP_JWT_ALLOW_ENV_FALLBACK", raising=False)
    sensitive_value = "super-secret-32-bytes-padding-leak"
    # env 配的是 sensitive_value；DB 是空（fake.stored=None）。prod 走到
    # 失败分支时，env 也不会被纳入 SECRET_RESOLVE_FAILED 的 params。
    settings = _settings(env="prod", secret=sensitive_value)
    fake = _FakeSessionBase()  # stored=None → DB 读不到
    resolver = JWTSecretResolver(settings, session_factory=lambda: fake)

    with pytest.raises(I18nError) as ei:
        asyncio.run(resolver.resolve())

    # params / 任何 locale 渲染 / str(e) 都不能包含敏感值
    assert sensitive_value not in ei.value.params.values()
    assert sensitive_value not in ei.value.localized(locale="en-US")
    assert sensitive_value not in ei.value.localized(locale="zh-CN")
    assert sensitive_value not in ei.value.localized(locale="zh-TW")
    assert sensitive_value not in str(ei.value)
