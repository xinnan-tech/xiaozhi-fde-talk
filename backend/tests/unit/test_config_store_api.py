"""· ConfigStore 提供同步只读公开 API，替代外部直接访问 _cache（M-008）。

engine / llm factory / asr factory / funasr_server / diagnostics 都直接读
get_config_store()._cache，破坏封装、难以 mock。ConfigStore.get_sync(key, default)
读缓存（不查 DB）替代之；调用方的 DEFAULTS 兜底仍在调用处。
"""
from __future__ import annotations

import inspect

from app.core.config_store import ConfigStore


def test_get_sync_returns_cached_value():
    store = ConfigStore()
    store._cache["test.key"] = "cached_value"
    assert store.get_sync("test.key") == "cached_value"


def test_get_sync_returns_default_for_missing_key():
    store = ConfigStore()
    assert store.get_sync("nope.key") is None
    assert store.get_sync("nope.key", default="fallback") == "fallback"


def test_get_sync_is_synchronous():
    """get_sync 必须同步（不返回 coroutine），与 async get 区分。"""
    assert not inspect.iscoroutinefunction(ConfigStore.get_sync)


def test_get_sync_does_not_access_db():
    """get_sync 不查 DB——只读缓存。调用 DB 会违反 warm 后的同步契约。"""
    store = ConfigStore()
    store._cache["k"] = "v"
    # 即便 store 未 warm（_refresh_cache 未调），get_sync 也不应触碰 DB
    #（这里没 db attribute 调用；若实现错误调 DB 会在无 engine 时抛）
    assert store.get_sync("k") == "v"