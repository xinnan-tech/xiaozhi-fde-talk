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
    """API Key 同时属于 SENSITIVE_KEYS 与 REQUIRED_STRING_KEYS，PUT 空值要走
    "不动原值"契约而非 400——前提是缓存里已有非空值。

    修复前 set_many 顺序：validate_value → SENSITIVE_KEYS skip → 必填串会被拦。
    修复后顺序：缓存非空 → skip；缓存为空 → validate_value 拒绝。
    """
    store._cache = {"asr.doubao_stream.api_key": "old-real-key"}
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

    await store.set_many({"asr.doubao_stream.api_key": ""})

    # 原值未被覆盖
    assert store._cache["asr.doubao_stream.api_key"] == "old-real-key"
    # DB 未写入
    session.execute.assert_not_called()
    # 广播触发一次但 changed 为空（set_many 始终调一次 _notify，跳过键不进 changed）
    assert notified == [set()]


async def test_set_many_rejects_empty_sensitive_when_cache_already_empty(store, monkeypatch):
    """缓存里 API Key 已为空（首部署 / 切换 provider 后），
    再次 PUT 空值必须走 validate_value 拦下 config.invalid_required_string，
    否则 admin 提交空表单拿虚假 200，错误要等到 doubao 首握才显形。
    """
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    store._cache = {"asr.doubao_stream.api_key": ""}

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(I18nError) as ei:
        await store.set_many({"asr.doubao_stream.api_key": ""})
    assert ei.value.code == Keys.CONFIG_INVALID_REQUIRED_STRING.value
    assert ei.value.params["name"] == "asr.doubao_stream.api_key"
    # 缓存值未动
    assert store._cache["asr.doubao_stream.api_key"] == ""


async def test_set_many_rejects_whitespace_required_string(store, monkeypatch):
    """全空格 API Key 不属于 SENSITIVE_KEYS 跳过路径（非 == ''），
    必须被 REQUIRED_STRING_KEYS 校验拦下。"""
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    store._cache = {"asr.doubao_stream.api_key": "old"}

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(I18nError) as ei:
        await store.set_many({"asr.doubao_stream.api_key": "   "})
    assert ei.value.code == Keys.CONFIG_INVALID_REQUIRED_STRING.value
    # 原值未被破坏
    assert store._cache["asr.doubao_stream.api_key"] == "old"


def test_sanitize_loaded_values_warns_on_empty_required_strings(store, caplog):
    """#138 P1-3: 老部署 DB 已有 '' 的必填字段，加载时必须 warn。

    不能简单回退 DEFAULTS（DEFAULTS 自己也是 ''），留 cache 真相 + warn 由
    provider 构造路径 ValueError 兜底。
    """
    import logging
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.api_key": "   \t",
        "asr.doubao_stream.language": "zh-CN",  # 非必填，不该 warn
    }

    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        sanitized = _sanitize_loaded_values(loaded)

    warned_keys = {
        rec.message
        for rec in caplog.records
        if "必填字段" in rec.message or "必填鉴权" in rec.message or "需 admin" in rec.message
    }
    # 必填 key 触发 warn
    assert any("asr.doubao_stream.api_key" in m for m in warned_keys)
    # 非必填 key 不该 warn（仅抽样：language）
    assert not any("asr.doubao_stream.language" in m for m in warned_keys)
    # 必填字段透传——不回退（DEFAULTS 也是 ''），由 provider 构造路径兜底
    assert sanitized["asr.doubao_stream.api_key"] == "   \t"


async def test_warm_skips_invalid_defaults(store, monkeypatch, caplog):
    """warm() 种入前 validate_value，DEFAULTS 中空字符串必填字段
    （如豆包 api_key）不应被无声写入 DB。

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
    # warn 命中必填字段
    warned = [r.message for r in caplog.records if "跳过种入" in r.message]
    assert any("asr.doubao_stream.api_key" in m for m in warned)

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


# ---- 豆包 ASR 1.0 → 2.0 协议升级迁移 ----
#
# PR #224 引入 API Key 协议升级，老 DB 里 appid + access_token 双字段被
# api_key 单字段取代。_sanitize_loaded_values 必须把这些行迁移到 2.0 形态，
# 否则 warm() 后 cache miss → doubao_stream.py:103 抛 "api_key 未配置"，
# 升级用户 100% 失败。


def test_sanitize_migrates_doubao_1_0_access_token_when_appid_present():
    """老 DB 行 appid + access_token 都非空、api_key 为空 → access_token 复制到 api_key。

    旧 key 同步从返回 dict 里 pop，warm() 据此 DELETE DB 行避免死数据堆积。
    """
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.appid": "old-appid-123",
        "asr.doubao_stream.access_token": "old-token-456",
        "asr.doubao_stream.api_key": "",
    }
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.api_key"] == "old-token-456"
    assert "asr.doubao_stream.appid" not in sanitized
    assert "asr.doubao_stream.access_token" not in sanitized


def test_sanitize_skips_migration_when_api_key_already_present():
    """admin 已经手动填了 2.0 api_key → 不覆盖、warn 不发；旧 key 仍删（已是死字段）。"""
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.appid": "stale-appid",
        "asr.doubao_stream.access_token": "stale-token",
        "asr.doubao_stream.api_key": "ak-new",
    }
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.api_key"] == "ak-new"
    assert "asr.doubao_stream.appid" not in sanitized
    assert "asr.doubao_stream.access_token" not in sanitized


def test_sanitize_skips_migration_when_appid_missing():
    """只有 access_token 没 appid → 半坏配置，不迁移避免继承坏值。

    1.0 协议要两者都填，缺一即坏配置；admin 调试时看到原值更易定位。
    旧 key 仍删（已不在 ALL_B_KEYS）。
    """
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.access_token": "orphan-token",
        # appid 缺
        "asr.doubao_stream.api_key": "",
    }
    sanitized = _sanitize_loaded_values(loaded)
    # 没迁移：api_key 仍是空
    assert sanitized["asr.doubao_stream.api_key"] == ""
    assert "asr.doubao_stream.access_token" not in sanitized


def test_sanitize_skips_migration_when_access_token_empty():
    """access_token 空、appid 非空：同样属半坏配置，不迁移。"""
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.appid": "old-appid",
        "asr.doubao_stream.access_token": "",
        "asr.doubao_stream.api_key": "",
    }
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.api_key"] == ""
    assert "asr.doubao_stream.appid" not in sanitized


def test_sanitize_upgrades_legacy_resource_id_to_2_0_default():
    """DB resource_id == 1.0 默认值（用户没手动改过）→ 自动升级到 2.0 默认值。"""
    from app.core.config_store import (
        DEFAULTS, LEGACY_DOUBAO_1_0_RESOURCE_ID, _sanitize_loaded_values,
    )

    loaded = {"asr.doubao_stream.resource_id": LEGACY_DOUBAO_1_0_RESOURCE_ID}
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.resource_id"] == DEFAULTS[
        "asr.doubao_stream.resource_id"
    ]
    assert sanitized["asr.doubao_stream.resource_id"] == "volc.seedasr.sauc.duration"


def test_sanitize_does_not_overwrite_custom_resource_id():
    """DB resource_id 是非默认自定义值（用户手动配过的 1.0 特殊值或别的）→ 不动。"""
    from app.core.config_store import _sanitize_loaded_values

    loaded = {"asr.doubao_stream.resource_id": "volc.custom.something"}
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.resource_id"] == "volc.custom.something"


def test_sanitize_does_not_overwrite_already_2_0_default():
    """DB resource_id 已是 2.0 默认值 → 不动。"""
    from app.core.config_store import DEFAULTS, _sanitize_loaded_values

    loaded = {"asr.doubao_stream.resource_id": DEFAULTS["asr.doubao_stream.resource_id"]}
    sanitized = _sanitize_loaded_values(loaded)
    assert sanitized["asr.doubao_stream.resource_id"] == "volc.seedasr.sauc.duration"


def test_sanitize_legacy_migration_logs_warning(store, caplog):
    """迁移时必须 warn，让 admin 看到 1.0 旧配置已自动迁移。"""
    import logging
    from app.core.config_store import _sanitize_loaded_values

    loaded = {
        "asr.doubao_stream.appid": "old-appid",
        "asr.doubao_stream.access_token": "old-token",
        "asr.doubao_stream.resource_id": "volc.bigasr.sauc.duration",
    }
    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        _sanitize_loaded_values(loaded)
    # 凭证迁移 + resource_id 升级两条 warn
    cred_warned = any("豆包 ASR 1.0 凭证" in r.message for r in caplog.records)
    rid_warned = any("豆包 ASR 1.0 resource_id" in r.message for r in caplog.records)
    assert cred_warned, "凭证迁移缺少 warn"
    assert rid_warned, "resource_id 升级缺少 warn"


async def test_warm_runs_migration_end_to_end(store, monkeypatch):
    """端到端：老 DB 行（appid + access_token + 1.0 resource_id）→ warm() 后 cache
    含 api_key（值=原 access_token）、resource_id 已升级，旧 key 从 cache 消失。
    """
    # 模拟老 DB：有 appid/access_token 旧行、resource_id 是 1.0 默认值、其余 DEFAULTS 全有
    legacy_rows = list(DEFAULTS.items())
    legacy_rows = [
        ("asr.doubao_stream.appid", "old-appid-999"),
        ("asr.doubao_stream.access_token", "old-token-999"),
        ("asr.doubao_stream.resource_id", "volc.bigasr.sauc.duration"),  # 1.0 默认
    ] + [(k, v) for k, v in legacy_rows if not k.startswith("asr.doubao_stream.")]

    session = _make_session_with_rows(legacy_rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()

    # 凭证已迁移到 api_key
    assert store._cache["asr.doubao_stream.api_key"] == "old-token-999"
    # resource_id 已升级到 2.0 默认
    assert store._cache["asr.doubao_stream.resource_id"] == "volc.seedasr.sauc.duration"
    # 旧 key 从 cache 消失
    assert "asr.doubao_stream.appid" not in store._cache
    assert "asr.doubao_stream.access_token" not in store._cache


async def test_warm_keeps_existing_valid_values_after_migration(store, monkeypatch):
    """迁移不应影响其他合法 key——只动 legacy 行涉及的那几个。"""
    # 标准 DEFAULTS + 一条 legacy 行
    rows = list(DEFAULTS.items()) + [
        ("asr.doubao_stream.appid", "old-appid"),
        ("asr.doubao_stream.access_token", "old-token"),
    ]
    session = _make_session_with_rows(rows)
    session.add = MagicMock()
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    await store.warm()

    # 其他 DEFAULTS 全部保留
    assert store._cache["llm.type"] == "openai"
    assert store._cache["asr.funasr_server.language"] == "zh"
    assert store._cache["session.grace_period_s"] == "60.0"
    # 豆包迁移正常
    assert store._cache["asr.doubao_stream.api_key"] == "old-token"
    assert "asr.doubao_stream.appid" not in store._cache
