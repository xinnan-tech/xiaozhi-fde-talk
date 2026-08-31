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


# ---- 加载层脏值收敛：warm() / _refresh_cache() 必须 sanitize ENUM/BOOL/NUMERIC ----
#
# PR #141 修复：写入层校验挡住新脏值落库，但 DB 已有行（手动改 DB / 迁移脚本
# 遗漏 / 镜像回放等历史脏值）若放任进缓存，首次 create_llm() 在 factory.py:54
# 抛 ValueError 会把全站 LLM 调打成 500。这里验证加载层会把脏值回退到 DEFAULTS。


def _make_session_with_rows(rows):
    """构造一个返回 rows 给 select(... where key in ALL_B_KEYS) 的 AsyncMock session。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        MagicMock(key=k, value=v) for k, v in rows
    ]
    session.execute = AsyncMock(return_value=result)
    return session


async def test_warm_reverts_dirty_llm_type(store, monkeypatch, caplog):
    """DB 已有 llm.type=anthropic（脏值），warm 后 cache 应回退到 DEFAULTS=openai。"""
    dirty_rows = list(DEFAULTS.items())
    # 注入脏值：anthropic 不在 ENUM_KEYS["llm.type"] 内
    dirty_rows = [(k, "anthropic" if k == "llm.type" else v) for k, v in dirty_rows]

    session = _make_session_with_rows(dirty_rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    import logging
    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        await store.warm()
    assert store._cache["llm.type"] == DEFAULTS["llm.type"]
    assert store._cache["llm.type"] == "openai"
    # 告警里带 key 与脏值，便于运维定位
    assert any("llm.type" in rec.message and "anthropic" in rec.message for rec in caplog.records)


async def test_warm_reverts_dirty_asr_language(store, monkeypatch):
    """DB 已有 asr.funasr_server.language=fr（脏值），warm 后回退到 zh。"""
    dirty_rows = [
        (k, "fr" if k == "asr.funasr_server.language" else v)
        for k, v in DEFAULTS.items()
    ]
    session = _make_session_with_rows(dirty_rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()
    assert store._cache["asr.funasr_server.language"] == DEFAULTS["asr.funasr_server.language"]
    assert store._cache["asr.funasr_server.language"] == "zh"


async def test_warm_reverts_dirty_numeric_value(store, monkeypatch):
    """DB 已有 session.grace_period_s=-5（脏值），warm 后回退到 60.0。"""
    dirty_rows = [
        (k, "-5" if k == "session.grace_period_s" else v)
        for k, v in DEFAULTS.items()
    ]
    session = _make_session_with_rows(dirty_rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()
    assert store._cache["session.grace_period_s"] == DEFAULTS["session.grace_period_s"]
    assert store._cache["session.grace_period_s"] == "60.0"


async def test_warm_reverts_dirty_bool_value(store, monkeypatch):
    """DB 已有 auth.allow_registration=yes（脏值），warm 后回退到 false。"""
    dirty_rows = [
        (k, "yes" if k == "auth.allow_registration" else v)
        for k, v in DEFAULTS.items()
    ]
    session = _make_session_with_rows(dirty_rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()
    assert store._cache["auth.allow_registration"] == DEFAULTS["auth.allow_registration"]
    assert store._cache["auth.allow_registration"] == "false"


async def test_warm_keeps_valid_values(store, monkeypatch):
    """DB 里的值本身合法时不应被改动。"""
    session = _make_session_with_rows(list(DEFAULTS.items()))
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()
    assert store._cache["llm.type"] == "openai"
    assert store._cache["asr.funasr_server.language"] == "zh"
    assert store._cache["auth.allow_registration"] == "false"
    assert store._cache["session.grace_period_s"] == "60.0"


async def test_refresh_cache_sanitizes(store, monkeypatch):
    """_refresh_cache() 自身也走 sanitize（不只 warm）；invalidate 后续重读仍兜底。"""
    from app.core.config_store import _sanitize_loaded_values

    dirty_rows = [
        (k, "anthropic" if k == "llm.type" else v)
        for k, v in DEFAULTS.items()
    ]
    session = _make_session_with_rows(dirty_rows)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store._refresh_cache()
    # _sanitize_loaded_values 已把 llm.type 改回 openai
    assert store._cache["llm.type"] == "openai"
    # 其他 key 原样保留
    assert store._cache["llm.base_url"] == DEFAULTS["llm.base_url"]


def test_sanitize_loaded_values_passthrough():
    """非受控 key（不在 ENUM/BOOL/NUMERIC 表内）原样保留——它们只走放行分支。"""
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "llm.base_url": "https://example.com",
        "llm.api_key": "sk-xxx",
        "asr.funasr_server.ws_url": "wss://localhost:10096",
    }
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized == loaded  # 完全透传


def test_sanitize_loaded_values_reverts_enum():
    """枚举脏值（anthropic / 乱写 / 空串）必须回退到 DEFAULTS。"""
    from app.core.config_store import _sanitize_loaded_values

    for bad in ("anthropic", "google", "totally_fake", ""):
        loaded = {"llm.type": bad}
        sanitized = _sanitize_loaded_values(loaded)
        assert sanitized["llm.type"] == DEFAULTS["llm.type"]


def test_sanitize_loaded_values_reverts_bool():
    from app.core.config_store import _sanitize_loaded_values

    sanitized = _sanitize_loaded_values({"auth.allow_registration": "yes"})
    assert sanitized["auth.allow_registration"] == DEFAULTS["auth.allow_registration"]


def test_sanitize_loaded_values_reverts_numeric_negative():
    """负数 / 0 都被 v <= 0 拦下，必须回退。"""
    from app.core.config_store import _sanitize_loaded_values

    sanitized = _sanitize_loaded_values({"session.grace_period_s": "0"})
    assert sanitized["session.grace_period_s"] == DEFAULTS["session.grace_period_s"]


def test_sanitize_loaded_values_reverts_numeric_nan():
    """NaN 字符串（绕过 int/float 转换但实际是非数）也应回退——但 validate_value
    在解析时 raise（ValueError 转 I18nError），所以走 except 分支回退。"""
    from app.core.config_store import _sanitize_loaded_values

    sanitized = _sanitize_loaded_values({"coach.pause_s": "nan"})
    assert sanitized["coach.pause_s"] == DEFAULTS["coach.pause_s"]
