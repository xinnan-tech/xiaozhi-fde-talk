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
        sanitized, _ = _sanitize_loaded_values(loaded)

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
    sanitized, _ = _sanitize_loaded_values(loaded)
    assert sanitized == loaded  # 完全透传


def test_sanitize_loaded_values_reverts_enum():
    """枚举脏值（anthropic / 乱写 / 空串）必须回退到 DEFAULTS。"""
    from app.core.config_store import _sanitize_loaded_values

    for bad in ("anthropic", "google", "totally_fake", ""):
        loaded = {"llm.type": bad}
        sanitized, _ = _sanitize_loaded_values(loaded)
        assert sanitized["llm.type"] == DEFAULTS["llm.type"]


def test_sanitize_loaded_values_reverts_bool():
    from app.core.config_store import _sanitize_loaded_values

    sanitized, _ = _sanitize_loaded_values({"auth.allow_registration": "yes"})
    assert sanitized["auth.allow_registration"] == DEFAULTS["auth.allow_registration"]


def test_sanitize_loaded_values_reverts_numeric_negative():
    """负数 / 0 都被 v <= 0 拦下，必须回退。"""
    from app.core.config_store import _sanitize_loaded_values

    sanitized, _ = _sanitize_loaded_values({"session.grace_period_s": "0"})
    assert sanitized["session.grace_period_s"] == DEFAULTS["session.grace_period_s"]


def test_sanitize_loaded_values_reverts_numeric_nan():
    """NaN 字符串（绕过 int/float 转换但实际是非数）也应回退——但 validate_value
    在解析时 raise（ValueError 转 I18nError），所以走 except 分支回退。"""
    from app.core.config_store import _sanitize_loaded_values

    sanitized, _ = _sanitize_loaded_values({"coach.pause_s": "nan"})
    assert sanitized["coach.pause_s"] == DEFAULTS["coach.pause_s"]


def test_sanitize_loaded_values_reverts_numeric_overflow():
    """#201: 老部署 DB 若已写入 jwt_expire_minutes=99999999999（admin UI 早期未
    校验时落库），warm() 必须回退到 DEFAULTS，否则服务一启动 token.py 立即
    OverflowError /auth/login 全站 500。走 validate_value → max 校验抛 I18nError →
    sanitize except 分支回退。
    """
    from app.core.config_store import _sanitize_loaded_values

    sanitized, _ = _sanitize_loaded_values({"auth.jwt_expire_minutes": "99999999999"})
    assert sanitized["auth.jwt_expire_minutes"] == DEFAULTS["auth.jwt_expire_minutes"]
    assert sanitized["auth.jwt_expire_minutes"] == "10080"  # 当前默认

    sanitized, _ = _sanitize_loaded_values({"session.max_concurrent": "999999"})
    assert sanitized["session.max_concurrent"] == DEFAULTS["session.max_concurrent"]
    assert sanitized["session.max_concurrent"] == "10"

    sanitized, _ = _sanitize_loaded_values({"auth.refresh_token_expire_days": "99999"})
    assert sanitized["auth.refresh_token_expire_days"] == DEFAULTS["auth.refresh_token_expire_days"]
    assert sanitized["auth.refresh_token_expire_days"] == "30"


def test_sanitize_loaded_values_accepts_numeric_at_max():
    """边界值（= max）必须保留——避免 sanitize 把合法上限值误回退。"""
    from app.core.config_store import NUMERIC_MAX_VALUE, _sanitize_loaded_values

    sanitized, _ = _sanitize_loaded_values({
        "auth.jwt_expire_minutes": str(NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"]),
    })
    assert sanitized["auth.jwt_expire_minutes"] == str(NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"])

    sanitized, _ = _sanitize_loaded_values({
        "session.max_concurrent": str(NUMERIC_MAX_VALUE["session.max_concurrent"]),
    })
    assert sanitized["session.max_concurrent"] == str(NUMERIC_MAX_VALUE["session.max_concurrent"])


def test_sanitize_loaded_values_returns_reverted_keys():
    """#201: warm() / _refresh_cache() 一次性 banner 需要 reverted 列表。
    没脏值时返空列表，有脏值时返 key 列表（供 banner 渲染）。
    """
    from app.core.config_store import _sanitize_loaded_values

    sanitized, reverted = _sanitize_loaded_values({"auth.jwt_expire_minutes": "10080"})
    assert reverted == []
    assert sanitized == {"auth.jwt_expire_minutes": "10080"}

    sanitized, reverted = _sanitize_loaded_values({"auth.jwt_expire_minutes": "99999999999"})
    assert reverted == ["auth.jwt_expire_minutes"]
    assert sanitized["auth.jwt_expire_minutes"] == DEFAULTS["auth.jwt_expire_minutes"]


async def test_refresh_cache_emits_banner_for_reverted_keys(store, monkeypatch, caplog):
    """#201: admin 部署后必须在启动日志里看到「哪些 key 被偷偷改回默认」，
    否则下次再写同一个错值还会踩坑。
    """
    import logging

    dirty_rows = [
        (k, "99999999999" if k == "auth.jwt_expire_minutes" else v)
        for k, v in DEFAULTS.items()
    ]
    session = _make_session_with_rows(dirty_rows)
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with caplog.at_level(logging.WARNING, logger="app.core.config_store"):
        await store._refresh_cache()

    # 一次性 banner 含回退 key 列表
    banner_msgs = [r.message for r in caplog.records if "回退" in r.message and "banner" not in r.message]
    banner = [m for m in banner_msgs if "DEFAULTS" in m and "auth.jwt_expire_minutes" in m]
    assert banner, f"应有一条回退 banner 含 'auth.jwt_expire_minutes'，实际: {banner_msgs}"
    # 缓存值已回退
    assert store._cache["auth.jwt_expire_minutes"] == DEFAULTS["auth.jwt_expire_minutes"]


async def test_set_many_rejects_jwt_expire_overflow_via_admin_path(store, monkeypatch):
    """#201 端到端：admin UI PUT /admin/config/auth 链路（routes/admin_config.py:133
    调 set_many）必须拒绝超大值。仅测 set_many 入口——避免 validate_value / set_many
    未来解耦后测试仍绿但 500 复现。
    """
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    store._cache = {}
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(I18nError) as ei:
        await store.set_many({"auth.jwt_expire_minutes": "99999999999"})
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    assert ei.value.params["name"] == "auth.jwt_expire_minutes"


async def test_jwt_expire_at_max_does_not_overflow_datetime():
    """#201 下游契约：上限 43200 分钟（30 天）必须远低于 datetime 容量，
    保证 token.py:78 `now + timedelta(minutes=cfg)` 不抛 OverflowError。
    锁住这条边界——若未来有人放宽 NUMERIC_MAX_VALUE 而忘了下游影响，
    本测试会因为日期越界而失败。
    """
    from datetime import datetime, timedelta, timezone

    from app.core.config_store import NUMERIC_MAX_VALUE
    max_minutes = NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"]
    # 数值上能相加；不会 OverflowError；exp 不超 datetime.maxyear（9999）
    exp = datetime.now(timezone.utc) + timedelta(minutes=max_minutes)
    assert exp.year < 9999, f"max_minutes={max_minutes} 越界到 {exp.year} 年"


async def test_get_max_concurrent_caps_at_max_value(monkeypatch):
    """#201 防御：validate_value 之外，runtime get_max_concurrent 也钳到上限。
    DB 直改 / 镜像回放绕过写入校验时，仍能自保。
    """
    from app.core.config_store import NUMERIC_MAX_VALUE, get_config_store, get_max_concurrent

    store = get_config_store()
    store._cache = {"session.max_concurrent": "9999999"}  # 远超上限

    capped = await get_max_concurrent()
    assert capped == NUMERIC_MAX_VALUE["session.max_concurrent"]


async def test_get_max_concurrent_accepts_max_value(monkeypatch):
    """边界值（= max）必须原样返回，不被 min() 误钳到 max-1。"""
    from app.core.config_store import NUMERIC_MAX_VALUE, get_config_store, get_max_concurrent

    store = get_config_store()
    store._cache = {"session.max_concurrent": str(NUMERIC_MAX_VALUE["session.max_concurrent"])}

    capped = await get_max_concurrent()
    assert capped == NUMERIC_MAX_VALUE["session.max_concurrent"]


async def test_get_max_concurrent_clamps_below_one():
    """老契约保留：<1 时钳到 1（不抛），让单用户部署也能开访谈。"""
    from app.core.config_store import get_config_store, get_max_concurrent

    store = get_config_store()
    store._cache = {"session.max_concurrent": "0"}

    capped = await get_max_concurrent()
    assert capped == 1
