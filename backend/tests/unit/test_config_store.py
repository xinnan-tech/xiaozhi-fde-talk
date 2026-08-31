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


async def test_set_many_skips_empty_sensitive_before_required_check(store, monkeypatch):
    """#138 P1-1: asr.doubao_stream.access_token 同时属于 SENSITIVE_KEYS 与
    REQUIRED_STRING_KEYS，PUT 空值要走"不动原值"契约而非 400。

    修复前 set_many 顺序：validate_value → SENSITIVE_KEYS skip → 必填串会被拦。
    修复后顺序：SENSITIVE_KEYS skip → validate_value → 空值跳过保持原值。
    """
    store._cache = {"asr.doubao_stream.access_token": "old-real-token"}
    notified: list[set[str]] = []

    def _on_change(ks):
        notified.append(ks)

    store.subscribe(_on_change)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    # 任何 execute 调用都返回空——不应被触发（敏感字段空值被跳过）
    noop_result = MagicMock()
    noop_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=noop_result)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.set_many({"asr.doubao_stream.access_token": ""})

    # 原值未被覆盖
    assert store._cache["asr.doubao_stream.access_token"] == "old-real-token"
    # DB 未写入
    session.execute.assert_not_called()
    # 广播触发一次但 changed 为空（set_many 始终调一次 _notify，跳过键不进 changed）
    assert notified == [set()]


async def test_set_many_rejects_whitespace_required_string(store, monkeypatch):
    """#138: 全空格 access_token 不属于 SENSITIVE_KEYS 跳过路径（非 == ''），
    必须被 REQUIRED_STRING_KEYS 校验拦下。"""
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    store._cache = {"asr.doubao_stream.access_token": "old"}

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(I18nError) as ei:
        await store.set_many({"asr.doubao_stream.access_token": "   "})
    assert ei.value.code == Keys.CONFIG_INVALID_REQUIRED_STRING.value
    # 原值未被破坏
    assert store._cache["asr.doubao_stream.access_token"] == "old"


def test_sanitize_loaded_values_warns_on_empty_required_strings(store, caplog):
    """#138 P1-3: 老部署 DB 已有 '' 的必填字段，加载时必须 warn。

    不能简单回退 DEFAULTS（DEFAULTS 自己也是 ''），留 cache 真相 + warn 由
    provider 构造路径 ValueError 兜底。
    """
    import logging

    store._cache = {
        "asr.doubao_stream.appid": "",
        "asr.doubao_stream.access_token": "   \t",
        "asr.doubao_stream.language": "zh-CN",  # 非必填，不该 warn
    }

    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        store._sanitize_loaded_values()

    warned_keys = {
        rec.message
        for rec in caplog.records
        if "必填字段" in rec.message or "必填鉴权" in rec.message or "需 admin" in rec.message
    }
    # 两个必填 key 都触发 warn
    assert any("asr.doubao_stream.appid" in m for m in warned_keys)
    assert any("asr.doubao_stream.access_token" in m for m in warned_keys)
    # 非必填 key 不该 warn（仅抽样：language）
    assert not any("asr.doubao_stream.language" in m for m in warned_keys)
    # cache 值未被动——留给 provider 构造路径判断
    assert store._cache["asr.doubao_stream.appid"] == ""
    assert store._cache["asr.doubao_stream.access_token"] == "   \t"


async def test_warm_skips_invalid_defaults(store, monkeypatch, caplog):
    """#138 P1-2: warm() 种入前 validate_value，DEFAULTS 中空字符串必填字段
    （如豆包 appid/access_token）不应被无声写入 DB。

    预期：日志 warn + 该 key 不出现在 cache（与 cache miss 等价，由 provider
    构造路径通过 get_sync 取到 None 触发 ValueError 兜底）。
    """
    import logging
    from app.core.config_store import REQUIRED_STRING_KEYS

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    # 第一次 query：DB 空 → 全 missing
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    # 第二次 query（refresh）：空字符串必填字段不写入，其他 DEFAULTS 全有
    seeded = [
        MagicMock(key=k, value=v) for k, v in DEFAULTS.items()
        if k not in REQUIRED_STRING_KEYS
    ]
    full_result = MagicMock()
    full_result.scalars.return_value.all.return_value = seeded
    session.execute = AsyncMock(side_effect=[empty_result, full_result])
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        await store.warm()

    # 必填字段未进 cache（跳过种入）
    for k in REQUIRED_STRING_KEYS:
        assert k not in store._cache, f"{k} 应被跳过但出现在 cache"
    # warn 至少命中两个必填字段
    warned = [r.message for r in caplog.records if "跳过种入" in r.message]
    assert any("asr.doubao_stream.appid" in m for m in warned)
    assert any("asr.doubao_stream.access_token" in m for m in warned)

