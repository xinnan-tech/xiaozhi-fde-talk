"""ConfigStore 单测：warm / get / set / set_many / singleton。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.config_store import (
    ALL_B_KEYS, ConfigStore, DEFAULTS, SENSITIVE_KEYS, get_config_store,
)


@pytest.fixture
def store():
    ConfigStore._instance = None
    return ConfigStore()


async def test_warm_seeds_missing_keys(store, monkeypatch):
    """DB 空 → warm 后所有 DEFAULTS key 都在 cache 里。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    # 第一次 query：DB 空 → 全 missing
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    # 第二次 query（refresh）：全有
    full_result = MagicMock()
    full_result.scalars.return_value.all.return_value = [
        MagicMock(key=k, value=v) for k, v in DEFAULTS.items()
    ]
    session.execute = AsyncMock(side_effect=[empty_result, full_result])
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)

    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()
    assert len(store._cache) == len(DEFAULTS)
    # 默认 base_url 已改为国内百炼入口（之前是空字符串）
    assert store._cache["llm.base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # idle_timeout_s 默认 30 分钟（之前是 120 秒，用户原话要求放宽）
    assert store._cache["session.idle_timeout_s"] == "1800.0"


async def test_get_returns_none_for_missing(store, monkeypatch):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)
    assert await store.get("llm.nonexistent") is None


async def test_set_updates_cache_and_notifies(store, monkeypatch):
    store._cache = {"llm.base_url": ""}
    notified = []

    def _on_change(ks):
        notified.append(ks)

    store.subscribe(_on_change)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = AsyncMock(return_value=MagicMock(value=""))
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.set("llm.base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert store._cache["llm.base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert notified == [{"llm.base_url"}]


async def test_set_many_writes_and_notifies(store, monkeypatch):
    """批量写入：DB 写入 + 缓存更新 + 广播。敏感字段空-跳过由集成测试覆盖。"""
    store._cache = {"llm.base_url": ""}
    notified = []

    def _on_change(ks):
        notified.append(ks)

    store.subscribe(_on_change)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.set_many({"llm.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"})
    assert store._cache["llm.base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert notified == [{"llm.base_url"}]


def test_singleton():
    assert get_config_store() is get_config_store()


def test_subscribers_are_weakref(store):
    """subscriber 对象释放后自动从 WeakSet 消失（验证 __init__ 用 WeakSet 而非 list）。"""
    import gc

    def cb(ks):  # noqa: ARG001
        pass

    store.subscribe(cb)
    assert cb in store._subscribers
    del cb
    gc.collect()
    assert len(store._subscribers) == 0
