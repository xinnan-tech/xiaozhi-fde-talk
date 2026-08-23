"""异步 config 取值 sanity check：get_llm_config / get_asr_config / get_coach_config
等便捷函数能成功从 ConfigStore 读到（mock DB）。

保证适配层 + 服务层不再从 get_settings() 拿 B 类字段——走 ConfigStore 间接层。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config_store import (
    ConfigStore,
    DEFAULTS,
    get_asr_config,
    get_auth_runtime_config,
    get_coach_config,
    get_llm_config,
    get_session_runtime_config,
)


@pytest.fixture
def store_with_cache(monkeypatch):
    """预热好缓存的 ConfigStore（避免真打 DB）。"""
    ConfigStore._instance = None
    s = ConfigStore()
    # 灌入 DEFAULTS 镜像
    s._cache = dict(DEFAULTS)

    # 让所有便捷函数拿同一个实例
    monkeypatch.setattr("app.core.config_store.get_config_store", lambda: s)

    # 替 SessionLocal（兜底用）
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)
    return s


async def test_get_llm_config_returns_four_keys(store_with_cache):
    cfg = await get_llm_config()
    assert set(cfg.keys()) == {"type", "base_url", "api_key", "model"}
    assert cfg["model"] == "qwen-plus"
    assert cfg["type"] == "openai"


async def test_get_asr_config_returns_expected_keys(store_with_cache):
    cfg = await get_asr_config()
    assert cfg["type"] == "funasr_server"
    assert cfg["sample_rate"] == 16000  # int 转换
    assert "ws_url" in cfg


async def test_get_coach_config_parses_mixed_numbers(store_with_cache):
    cfg = await get_coach_config()
    assert cfg["pause_s"] == 5.0
    assert cfg["max_pending_segments"] == 8
    assert cfg["min_interval_s"] == 10.0
    assert cfg["llm_timeout_s"] == 45.0


async def test_get_auth_runtime_config_returns_two(store_with_cache):
    cfg = await get_auth_runtime_config()
    assert cfg["jwt_expire_minutes"] == 1440
    assert cfg["allow_registration"] is False
    # P2-7: demo_password 不再走 ConfigStore（改密走 /admin/users/{id}/password）


async def test_get_session_runtime_config_returns_grace(store_with_cache):
    cfg = await get_session_runtime_config()
    assert cfg["grace_period_s"] == 60.0


def test_all_b_keys_includes_allow_registration():
    from app.core.config_store import ALL_B_KEYS
    assert "auth.allow_registration" in ALL_B_KEYS


def test_defaults_allow_registration_false():
    from app.core.config_store import DEFAULTS
    assert DEFAULTS["auth.allow_registration"] == "false"


def test_validate_bool_true_false_accepted():
    from app.core.config_store import validate_value
    validate_value("auth.allow_registration", "true")  # 不抛
    validate_value("auth.allow_registration", "false")  # 不抛


def test_validate_bool_invalid_rejected():
    import pytest
    from app.core.i18n.errors import I18nError
    from app.core.config_store import validate_value
    with pytest.raises(I18nError):
        validate_value("auth.allow_registration", "yes")


async def test_set_allow_registration_round_trip_with_real_db(monkeypatch):
    """端到端：真 sqlite 内存库走 ConfigStore.set → cache 写 + 校验 → get 读回。

    全 mock 会漏掉 key 名 typo（catalog 与 DEFAULTS 不一致）、upsert SQL 拼接错误
    等运行期才会暴露的问题。至少保留这一条走真 store。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.persistence.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)

    ConfigStore._instance = None
    s = ConfigStore.instance()
    await s.warm()
    # warm 后默认 false
    assert s.get_sync("auth.allow_registration") == "false"

    # 合法 true → 写 + 缓存更新
    await s.set("auth.allow_registration", "true")
    assert s.get_sync("auth.allow_registration") == "true"

    # 坏值应抛 I18nError，不动 cache
    from app.core.i18n.errors import I18nError
    with pytest.raises(I18nError):
        await s.set("auth.allow_registration", "maybe")
    assert s.get_sync("auth.allow_registration") == "true"

    await engine.dispose()
