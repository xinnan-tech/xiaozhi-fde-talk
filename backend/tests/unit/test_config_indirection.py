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
    assert cfg["demo_username"] == "admin"
    # P2-7: demo_password 不再走 ConfigStore（改密走 /admin/auth/password）


async def test_get_session_runtime_config_returns_grace(store_with_cache):
    cfg = await get_session_runtime_config()
    assert cfg["grace_period_s"] == 60.0
