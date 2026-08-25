"""DB 配置 KV 存储 + 内存缓存 + 失效广播单例。

设计要点：
- 21 个 B 类 key（前后端共用清单 ALL_B_KEYS）
- 启动期 warm() 一次性灌入内存；DB 缺失的 key 用 DEFAULTS 种入
- 单条 set() / 批量 set_many() 都走 DB + 内存 + 订阅者广播
- 敏感字段（SENSITIVE_KEYS）GET 返 None、空值 PUT 跳过——避免误清密钥
- 失败订阅者不影响主流程（异常吞掉 + log）
"""
from __future__ import annotations

import logging
import weakref
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from sqlalchemy import select

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.persistence.db import SessionLocal
from app.persistence.models import SystemConfig

logger = logging.getLogger(__name__)

# B 类 key 的合法清单（前后端共用）
# ASR 字段按 type 隔离存储：asr.funasr_server.* / asr.doubao_stream.*
ALL_B_KEYS: list[str] = [
    "llm.type", "llm.base_url", "llm.api_key", "llm.model", "llm.output_language",
    "asr.type",
    # FunASR Server
    "asr.funasr_server.language", "asr.funasr_server.sample_rate",
    "asr.funasr_server.ws_url", "asr.funasr_server.ws_verify_ssl",
    # Doubao Stream
    "asr.doubao_stream.language", "asr.doubao_stream.sample_rate",
    "asr.doubao_stream.appid", "asr.doubao_stream.access_token",
    "asr.doubao_stream.resource_id", "asr.doubao_stream.enable_multilingual",
    # Coach
    "coach.pause_s", "coach.max_pending_segments", "coach.min_interval_s", "coach.llm_timeout_s",
    "auth.jwt_expire_minutes", "auth.allow_registration", "auth.refresh_token_expire_days",
    "session.grace_period_s",
    "session.idle_timeout_s",
    "session.idle_check_interval_s",
    "session.liveness_window_s",
    "session.max_concurrent",
    "ocr.type", "ocr.base_url", "ocr.api_key", "ocr.secret_key", "ocr.model",
]

# 敏感字段（GET 返 null，PUT 空 = 不动）。只列 ALL_B_KEYS 内的键：
# 白名单外的键本来就不可写，列进去只会让 GET 组输出凭空多一个 null 字段。
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "llm.api_key",
    "ocr.api_key",
    "ocr.secret_key",
    "asr.doubao_stream.access_token",
    "system.jwt_secret",
})

# 数值 key 的类型表：写入前校验。坏值若落库，要到运行路径（登录的
# int(jwt_expire_minutes)、断连的 float(grace_period_s)）才抛 500，全站遭殃。
NUMERIC_KEYS: dict[str, type] = {
    "asr.funasr_server.sample_rate": int,
    "asr.doubao_stream.sample_rate": int,
    "coach.max_pending_segments": int,
    "auth.jwt_expire_minutes": int,
    "auth.refresh_token_expire_days": int,
    "session.max_concurrent": int,
    "coach.pause_s": float,
    "coach.min_interval_s": float,
    "coach.llm_timeout_s": float,
    "session.grace_period_s": float,
    "session.idle_timeout_s": float,
    "session.idle_check_interval_s": float,
    "session.liveness_window_s": float,
}

# 枚举 key 的合法清单：写入前校验。坏值若落库，admin 配置页会把脏值
# 显示给用户；运行时 llm.output_language 错值会让 LLM 报错或行为异常。
# LLM 输出语种从 app.core.i18n.lang_meta.derived_output_language_enum() 派生——
# 加语种只需改 _LANG_META 一处。
from app.core.i18n.lang_meta import derived_output_language_enum

ENUM_KEYS: dict[str, set[str]] = {
    # FunASR 实际支持 {zh, en, ja, ko, yue, auto}，但我们只把常用的 3 个
    # 暴露给管理员——粤语场景明确支持（用户需求），ja/ko 当前无需求。
    "asr.funasr_server.language": {"zh", "yue", "en"},
    # Doubao 语种：完整 locale 列表
    "asr.doubao_stream.language": {
        "zh-CN", "en-US", "ja-JP", "id-ID", "es-MX", "pt-BR", "de-DE",
        "fr-FR", "ko-KR", "fil-PH", "ms-MY", "th-TH", "ar-SA", "it-IT",
        "bn-BD", "el-GR", "nl-NL", "ru-RU", "tr-TR", "vi-VN", "pl-PL",
        "ro-RO", "ne-NP", "uk-UA", "yue-CN",
    },
    # LLM 输出语种：跟 ASR 是独立维度（详见 plan Task 2.5 注释）。
    "llm.output_language": derived_output_language_enum(),
    # OCR 模型类型：openai 兼容（qwen-vl、gpt-4o）或百度
    "ocr.type": {"openai", "baidu"},
}

# bool key 集合：写入前校验，只接受 "true" / "false"。
# 坏值若放行，运行时 bool(value) 在 truthy/falsy 边界行为诡异（如 "yes"→True），
# 注册开关注定踩坑。
BOOL_KEYS: frozenset[str] = frozenset({
    "auth.allow_registration",
    "asr.doubao_stream.enable_multilingual",
})


def validate_value(key: str, value: str) -> None:
    """key 写入校验：BOOL_KEYS / NUMERIC_KEYS / ENUM_KEYS 三类。其他 key 放行。

    布尔与枚举分支都走 I18nError(code, http_status=400)，让 admin 配置页 / API
    客户端拿到结构化的 code + params；数值分支保留 ValueError（仅 admin 后台
    CLI 路径，暂无对应 Keys）。
    """
    if key in BOOL_KEYS:
        if value not in ("true", "false"):
            # 占位用 {name}，避免与 t() 的 `key` 形参撞名（TypeError）。
            raise I18nError(
                Keys.CONFIG_INVALID_BOOL,
                http_status=400,
                name=key,
            )
        return
    if key in ENUM_KEYS:
        allowed = ENUM_KEYS[key]
        if value not in allowed:
            raise I18nError(
                Keys.CONFIG_INVALID_ENUM_VALUE,
                http_status=400,
                field=key,
                value=value,
                allowed=" / ".join(sorted(allowed)),
            )
        return
    typ = NUMERIC_KEYS.get(key)
    if typ is None:
        return
    try:
        v = typ(value)
    except ValueError:
        raise ValueError(
            f"{key} 须为{'正整数' if typ is int else '正数值'}：{value!r}"
        ) from None
    if v <= 0:
        raise ValueError(
            f"{key} 须为{'正整数' if typ is int else '正数值'}：{value!r}"
        )


# 默认值（首次 warm 时若 DB 缺则种入）
DEFAULTS: dict[str, str] = {
    "llm.type": "openai",
    "llm.base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "llm.api_key": "",
    "llm.model": "qwen-plus",
    "llm.output_language": "zh_cn",
    "asr.type": "funasr_server",
    # FunASR Server
    "asr.funasr_server.language": "zh",
    "asr.funasr_server.sample_rate": "16000",
    "asr.funasr_server.ws_url": "wss://localhost:10096",
    "asr.funasr_server.ws_verify_ssl": "false",
    # Doubao Stream
    "asr.doubao_stream.language": "zh-CN",
    "asr.doubao_stream.sample_rate": "16000",
    "asr.doubao_stream.appid": "",
    "asr.doubao_stream.access_token": "",
    "asr.doubao_stream.resource_id": "volc.bigasr.sauc.duration",
    "asr.doubao_stream.enable_multilingual": "false",
    "coach.pause_s": "5.0",
    "coach.max_pending_segments": "8",
    "coach.min_interval_s": "10.0",
    "coach.llm_timeout_s": "45.0",
    "auth.jwt_expire_minutes": "1440",
    "auth.allow_registration": "false",
    "auth.refresh_token_expire_days": "7",
    "session.grace_period_s": "60.0",
    "session.idle_timeout_s": "1800.0",
    "session.idle_check_interval_s": "30.0",
    "session.liveness_window_s": "60.0",
    # 全局同时活跃访谈上限（= FunASR 房间容量）。suspended 不占名额。
    "session.max_concurrent": "10",
    # OCR（默认使用百度 OCR，api_key 为 access_token）
    "ocr.type": "baidu",
    "ocr.base_url": "https://aip.baidubce.com",
    "ocr.api_key": "",
    "ocr.secret_key": "",
    "ocr.model": "general_basic",
}


class ConfigStore:
    """DB 配置 KV 存储 + 内存缓存 + 失效广播单例。"""

    _instance: Optional["ConfigStore"] = None

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._subscribers: weakref.WeakSet[Callable[[set[str]], None]] = weakref.WeakSet()

    @classmethod
    def instance(cls) -> "ConfigStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def warm(self) -> None:
        """启动期一次性灌入内存；DB 缺失的 key 用 DEFAULTS 种入。"""
        async with SessionLocal() as session:
            existing = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_B_KEYS)))
            have = {row.key: row.value for row in existing.scalars().all()}
            missing = [k for k in ALL_B_KEYS if k not in have]
            for k in missing:
                v = DEFAULTS[k]
                session.add(SystemConfig(key=k, value=v))
            if missing:
                await session.commit()
                logger.info("ConfigStore 种入 %d 个默认 key", len(missing))
        # 重读完整缓存
        await self._refresh_cache()

    async def _refresh_cache(self) -> None:
        async with SessionLocal() as session:
            existing = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_B_KEYS)))
            self._cache = {row.key: row.value for row in existing.scalars().all()}

    async def get(self, key: str) -> Optional[str]:
        if key not in self._cache:
            # cache miss → 打 DB；DB 读失败 fail-fast
            async with SessionLocal() as session:
                row = await session.get(SystemConfig, key)
                if row is None:
                    return None
                self._cache[key] = row.value
        return self._cache.get(key)

    def get_sync(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """同步读缓存中的配置值（不查 DB）。

        替代外部直接访问 _cache 私有属性。仅用于 warm 后、值已缓存的场景；
        key 不在缓存返回 default（不回退 DB——保持同步契约）。
        """
        return self._cache.get(key, default)

    async def get_group(self, prefix: str) -> dict[str, str]:
        """返 {key: value}（敏感字段返 None 表示"别显示原值"）。"""
        keys = [k for k in ALL_B_KEYS if k.startswith(prefix + ".")]
        result: dict[str, str] = {}
        for k in keys:
            if k in SENSITIVE_KEYS:
                result[k.split(".", 1)[1]] = None  # type: ignore[assignment]
            else:
                v = await self.get(k)
                if v is not None:
                    result[k.split(".", 1)[1]] = v
        return result  # type: ignore[return-value]

    async def get_many(self, keys: Iterable[str]) -> dict[str, Optional[str]]:
        return {k: await self.get(k) for k in keys}

    async def set(self, key: str, value: str) -> None:
        """单条写入；更新 DB + 内存 + 广播。"""
        if key not in ALL_B_KEYS:
            raise ValueError(f"unknown config key: {key}")
        validate_value(key, value)
        async with SessionLocal() as session:
            row = await session.get(SystemConfig, key)
            if row is None:
                row = SystemConfig(key=key, value=value)
                session.add(row)
            else:
                row.value = value
            await session.commit()
        self._cache[key] = value
        self._notify({key})

    async def set_many(self, items: dict[str, str]) -> None:
        """批量写入（事务）；敏感字段跳过空值。

        用方言级 upsert（INSERT ... ON CONFLICT DO UPDATE）取代 get-then-add：
        后者并发写同一缺失 key 会双读 None 双 add，commit 撞 PK 冲突。
        """
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        async with SessionLocal() as session:
            dialect = session.bind.dialect.name if session.bind else "sqlite"
            for key, value in items.items():
                if key not in ALL_B_KEYS:
                    raise ValueError(f"unknown config key: {key}")
                validate_value(key, value)
                # 敏感字段空值跳过
                if key in SENSITIVE_KEYS and value == "":
                    continue
                now = datetime.now(timezone.utc)
                if dialect == "mysql":
                    stmt = mysql_insert(SystemConfig).values(
                        key=key, value=value, updated_at=now
                    ).on_duplicate_key_update(value=value, updated_at=now)
                elif dialect == "postgresql":
                    stmt = pg_insert(SystemConfig).values(
                        key=key, value=value, updated_at=now
                    ).on_conflict_do_update(
                        index_elements=[SystemConfig.key],
                        set_={"value": value, "updated_at": now})
                else:  # sqlite
                    stmt = sqlite_insert(SystemConfig).values(
                        key=key, value=value, updated_at=now
                    ).on_conflict_do_update(
                        index_elements=[SystemConfig.key],
                        set_={"value": value, "updated_at": now})
                await session.execute(stmt)
            await session.commit()
        # 更新内存 + 广播
        changed: set[str] = set()
        for key, value in items.items():
            if key in SENSITIVE_KEYS and value == "":
                continue
            self._cache[key] = value
            changed.add(key)
        self._notify(changed)

    def subscribe(self, fn: Callable[[set[str]], None]) -> None:
        """注册配置变更回调（弱引用持有）。

        订阅者必须被强引用持有（模块级函数，或存活到所需生命周期的具名局部），
        否则会被 GC 静默移除。不支持 bound method（WeakSet 无法弱引用方法对象，
        add() 会抛 TypeError）。
        """
        self._subscribers.add(fn)

    def invalidate(self, keys: Optional[Iterable[str]] = None) -> None:
        """清缓存（None=全清）。手动失效（罕见）。"""
        if keys is None:
            self._cache.clear()
            return
        for k in keys:
            self._cache.pop(k, None)

    def _notify(self, changed_keys: set[str]) -> None:
        for sub in list(self._subscribers):
            try:
                sub(changed_keys)
            except Exception:  # noqa: BLE001
                logger.exception("ConfigStore 订阅回调执行失败：%s", sub)


# 模块级便捷函数
def get_config_store() -> ConfigStore:
    return ConfigStore.instance()


async def get_llm_config() -> dict[str, str]:
    s = get_config_store()
    return {
        "type": await s.get("llm.type") or "",
        "base_url": await s.get("llm.base_url") or "",
        "api_key": await s.get("llm.api_key") or "",
        "model": await s.get("llm.model") or "",
    }


async def get_asr_config() -> dict[str, str]:
    s = get_config_store()
    return {
        "type": await s.get("asr.type") or "funasr_server",
        "sample_rate": int(await s.get("asr.sample_rate") or "16000"),
        "ws_url": await s.get("asr.ws_url") or "",
    }


async def get_coach_config() -> dict[str, float | int]:
    s = get_config_store()
    return {
        "pause_s": float(await s.get("coach.pause_s") or "5.0"),
        "max_pending_segments": int(await s.get("coach.max_pending_segments") or "8"),
        "min_interval_s": float(await s.get("coach.min_interval_s") or "10.0"),
        "llm_timeout_s": float(await s.get("coach.llm_timeout_s") or "45.0"),
    }


async def get_auth_runtime_config() -> dict[str, object]:
    s = get_config_store()
    return {
        "jwt_expire_minutes": int(await s.get("auth.jwt_expire_minutes") or "1440"),
        "allow_registration": (await s.get("auth.allow_registration") or "false") == "true",
        "refresh_token_expire_days": int(await s.get("auth.refresh_token_expire_days") or "7"),
    }


async def get_session_runtime_config() -> dict[str, float]:
    s = get_config_store()
    return {
        "grace_period_s": float(await s.get("session.grace_period_s") or "60.0"),
        "idle_timeout_s": float(await s.get("session.idle_timeout_s") or "1800.0"),
        "idle_check_interval_s": float(await s.get("session.idle_check_interval_s") or "30.0"),
        "liveness_window_s": float(await s.get("session.liveness_window_s") or "60.0"),
    }


async def get_ocr_config() -> dict[str, str]:
    s = get_config_store()
    return {
        "type": await s.get("ocr.type") or "baidu",
        "base_url": await s.get("ocr.base_url") or "",
        "api_key": await s.get("ocr.api_key") or "",
        "secret_key": await s.get("ocr.secret_key") or "",
        "model": await s.get("ocr.model") or "",
    }


async def get_max_concurrent() -> int:
    """全局同时活跃访谈上限（= FunASR 房间容量）。

    读 session.max_concurrent；解析失败或 <1 一律钳到 1（否则谁也开不了访谈）。
    """
    s = get_config_store()
    try:
        return max(1, int(await s.get("session.max_concurrent") or "10"))
    except (TypeError, ValueError):
        return 10

