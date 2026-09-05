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
import math
import weakref
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

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
    "asr.doubao_stream.api_key",
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
    "asr.doubao_stream.api_key",
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

# 数值 key 的合法上限：超出会让运行时溢出、OOM 分配或逻辑失效（#201 系列）。
NUMERIC_MAX_VALUE: dict[str, int | float] = {
    # 30 天 = 43200 分钟；access token TTL 业务上限（更长应用 refresh 机制）
    "auth.jwt_expire_minutes": 30 * 24 * 60,
    # 365 天；refresh token 撤销表可接受的"用户不登录"最长窗口
    "auth.refresh_token_expire_days": 365,
    # 1000；FunASR 单机房间容量上限
    "session.max_concurrent": 1000,
    # 1000；engine.py:277 用作 segment buffer 阈值，无上限会让兜底永远不命中
    "coach.max_pending_segments": 1000,
    # 192000；专业音频最大标准采样率。超限触发 funasr_server/doubao_stream 的
    # silence_bytes 分配（sample_rate * 2 * tail_ms）OOM Killed，全站 ASR 中断
    "asr.funasr_server.sample_rate": 192000,
    "asr.doubao_stream.sample_rate": 192000,
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
    # LLM 提供方类型：跟 factory.py:_REGISTRY 对齐；任意脏值落库会让
    # create_llm() 在 factory.py:54 抛 ValueError，admin 端 PUT 链路上没有
    # catch 转 422，全站 LLM 调 500。在写入层校验一次性挡掉。
    "llm.type": {"openai", "stub"},
    # OCR 模型类型：openai 兼容（qwen-vl、gpt-4o）或百度
    "ocr.type": {"openai", "baidu"},
    # ASR 类型：set_many 过滤非激活字段时拼 f"asr.{active_asr_type}." 前缀，
    # 若 active_asr_type 是空白 / 未知字符串会把所有 asr.* 子字段静默丢弃，
    # 仍 200 返回「保存成功」——靠 ENUM 校验在写入前挡掉，admin 收到 400 而
    # 不是丢配置。
    "asr.type": {"funasr_server", "doubao_stream"},
}

# URL key：scheme 必须在白名单 + 主机段必填 + 拒整段前后空白（写入前校验）；空串放行，让 admin PUT "" 清空 ws_url。
URL_KEYS: dict[str, set[str]] = {
    "asr.funasr_server.ws_url": {"ws", "wss"},
    "llm.base_url": {"http", "https"},
    "ocr.base_url": {"http", "https"},
}

# bool key 集合：写入前校验，只接受 "true" / "false"。
# 坏值若放行，运行时 bool(value) 在 truthy/falsy 边界行为诡异（如 "yes"→True），
# 注册开关注定踩坑。
BOOL_KEYS: frozenset[str] = frozenset({
    "auth.allow_registration",
    "asr.doubao_stream.enable_multilingual",
})

# 必填鉴权字段：写入侧挡空白，避免首握失败时 admin 误判是服务挂。
REQUIRED_STRING_KEYS: frozenset[str] = frozenset({
    "asr.doubao_stream.api_key",
})


def validate_value(key: str, value: str) -> None:
    """key 写入校验：BOOL_KEYS / REQUIRED_STRING_KEYS / ENUM_KEYS / NUMERIC_KEYS
    四类。其他 key 放行。

    布尔 / 必填 / 枚举 / 数值分支都走 I18nError(code, http_status=400)，让 admin
    配置页 / API 客户端拿到结构化的 code + params。数值分支额外拦截
    float('nan' / 'inf' / 1e10000 等)——它们会绕过 `v <= 0` 判断直接落库，运
    行时才在 int()/float() 转换炸。改用 math.isfinite(v) 在解析后兜住所有浮点
    特殊值。
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
    if key in REQUIRED_STRING_KEYS:
        if not value or not value.strip():
            raise I18nError(
                Keys.CONFIG_INVALID_REQUIRED_STRING,
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
    if key in URL_KEYS:
        allowed_schemes = URL_KEYS[key]
        # 空串放行：admin PUT "" 清空 ws_url → runtime 走 funasr_server.py:144
        # 未配置即 fail-fast 路径；llm.base_url / ocr.base_url 同理。
        if value == "":
            return
        # 前后空白整段拒：runtime 传给 websockets.connect 的是
        # funasr_server.py:150 self._ws_url.rstrip("/")，不去前后空白，会带空
        # 格抛 InvalidURI；admin 在写入时拿不到结构化错因，故在写入层拒。
        if value != value.strip():
            raise I18nError(
                Keys.CONFIG_INVALID_ENUM_VALUE,
                http_status=400,
                field=key,
                value=value,
                allowed=" / ".join(f"{s}://host:port" for s in sorted(allowed_schemes)),
            )
        try:
            parsed = urlparse(value)
        except ValueError:
            # 未闭合的 '[' / 'ws://[invalid' 等 urlparse 抛 ValueError("Invalid IPv6 URL")，
            # 不包会沿裸传到 routes/admin_config.py 通用 except 转 422 + field=group——覆盖
            # 不到本分支新增的 400 + field=key 结构化反馈，且丢失 allowed 字段。
            raise I18nError(
                Keys.CONFIG_INVALID_ENUM_VALUE,
                http_status=400,
                field=key,
                value=value,
                allowed=" / ".join(f"{s}://host:port" for s in sorted(allowed_schemes)),
            )
        # parsed.hostname 优先于 parsed.netloc：urlparse("ws://:10095") 返 netloc=":10095" 非空
        # 但 hostname=None，仅端口无主机段——放行后 websockets.connect 抛 InvalidURI。
        if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
            raise I18nError(
                Keys.CONFIG_INVALID_ENUM_VALUE,
                http_status=400,
                field=key,
                value=value,
                allowed=" / ".join(f"{s}://host:port" for s in sorted(allowed_schemes)),
            )
        return
    typ = NUMERIC_KEYS.get(key)
    if typ is None:
        return
    # int / float 数值 key 走不同 i18n key——按类型给管理员「正整数 / 正数」
    # 文案，避免共占位符被硬塞英文字面量（详见 messages.py 注释）。
    err_key = (
        Keys.CONFIG_INVALID_POSITIVE_INTEGER
        if typ is int
        else Keys.CONFIG_INVALID_POSITIVE_NUMBER
    )
    try:
        v = typ(value)
    except (ValueError, TypeError):
        raise I18nError(
            err_key,
            http_status=400,
            name=key,
            value=value,
        ) from None
    # math.isfinite 兜住所有浮点特殊值（NaN / +Inf / -Inf / 1e10000）：
    # float('nan')/float('inf') 解析成功但 v <= 0 为 False 会落库，且字符串预
    # 检漏 +nan/+inf/科学记数法溢出。<= 0 单独判断覆盖负数与 0。
    if not math.isfinite(v) or v <= 0:
        raise I18nError(
            err_key,
            http_status=400,
            name=key,
            value=value,
        )
    # 上限校验（#201）：仅作用于 NUMERIC_MAX_VALUE 列出的 key。
    max_value = NUMERIC_MAX_VALUE.get(key)
    if max_value is not None and v > max_value:
        raise I18nError(
            Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE,
            http_status=400,
            name=key,
            value=value,
            max=max_value,
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
    "asr.doubao_stream.api_key": "",
    "asr.doubao_stream.resource_id": "volc.seedasr.sauc.duration",
    "asr.doubao_stream.enable_multilingual": "false",
    "coach.pause_s": "5.0",
    "coach.max_pending_segments": "8",
    "coach.min_interval_s": "10.0",
    "coach.llm_timeout_s": "45.0",
    "auth.jwt_expire_minutes": "10080",
    "auth.allow_registration": "false",
    "auth.refresh_token_expire_days": "30",
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


def _sanitize_loaded_values(loaded: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """加载层兜底：DB 已有行里若有脏值（手动改 DB / 迁移脚本遗漏 / 镜像回放等历史脏值），
    按 ENUM/BOOL/NUMERIC/URL 重新校验，命中失败回退到 DEFAULTS[k]。

    返回 (sanitized, reverted_keys)：reverted_keys 是本次回退的 key 列表，供
    warm() / _refresh_cache() 一次性打 banner 让 admin 部署后看到「哪些 key
    偷偷改回默认」（#201 系列：仅 logger.warning 单条会被淹没在启动日志里）。

    必填鉴权字段（REQUIRED_STRING_KEYS）空值仅 warn、不回退（DEFAULTS 自身也是 ""，
    无有效回退目标），由 provider 构造路径的 ValueError 兜底——但要让 admin 可见。

    非受控 key（不在 ENUM/BOOL/NUMERIC/URL 表内的）原样保留——它们只走 validate_value
    "放行"分支，重新校验无意义。
    """
    validated_keys = set(ENUM_KEYS) | set(BOOL_KEYS) | set(NUMERIC_KEYS) | set(URL_KEYS)
    sanitized: dict[str, str] = {}
    reverted: list[str] = []
    for k, v in loaded.items():
        if k in validated_keys:
            try:
                validate_value(k, v)
            except I18nError:
                if k in DEFAULTS:
                    logger.warning(
                        "ConfigStore 加载时发现脏值 %s=%r，已回退到 DEFAULTS=%r",
                        k, v, DEFAULTS[k],
                    )
                    sanitized[k] = DEFAULTS[k]
                    reverted.append(k)
                    continue
                # 拿不到 DEFAULTS：跳过避免后续运行路径炸 500（理论上 ALL_B_KEYS
                # 与 DEFAULTS key 一一对应，这里是兜底）。
                logger.warning(
                    "ConfigStore 加载时发现脏值 %s=%r 且无 DEFAULTS 可回退，跳过该 key",
                    k, v,
                )
                continue
        elif k in REQUIRED_STRING_KEYS and (v is None or not v.strip()):
            # 老部署 DB 若已存在空值必填字段（手工改 DB / 镜像回放 / 早期 bug
            # 落库），不回退 DEFAULTS（DEFAULTS 自己也是 ""），仅 warn 让 admin 可见，
            # 留 cache 真相由 provider 构造路径 ValueError 兜底。
            logger.warning(
                "ConfigStore 检测到 %s 值为 %r（必填字段），"
                "需 admin 在配置页补齐后 provider 才能正常握手",
                k, v,
            )
        sanitized[k] = v
    return sanitized, reverted


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
        """启动期一次性灌入内存；DB 缺失的 key 用 DEFAULTS 种入。

        DEFAULTS 中若有空字符串类必填字段（如豆包 api_key 没有合法
        默认），validate_value 会拒——跳过种入并 warn，让 DB 留空由 admin 通过
        配置页补齐，避免无声写入"无效值"。其他 key 的脏 DEFAULTS（URL / ENUM /
        BOOL / NUMERIC 写错）属配置 bug，必须 fail-fast 抛出——首次启动通道与
        admin PUT 通道同等对待。

        加载完成后遍历一次 ENUM_KEYS / BOOL_KEYS / NUMERIC_KEYS，命中校验失败
        的脏值（手动改 DB / 迁移脚本遗漏 / 镜像回放等历史脏值）回退到 DEFAULTS
        并 logger.warning——避免首次 create_llm() 在 factory.py:54 抛 ValueError
        把全站 LLM 调打成 500（get_llm() 是 interviews.py / coaching/engine.py
        等热路径的必经节点）。老数据无需迁移脚本就能收敛。

        """
        async with SessionLocal() as session:
            existing = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_B_KEYS)))
            have = {row.key: row.value for row in existing.scalars().all()}
            missing = [k for k in ALL_B_KEYS if k not in have]
            for k in missing:
                v = DEFAULTS[k]
                try:
                    validate_value(k, v)
                except I18nError:
                    # 必填字段（豆包 api_key 等）DEFAULTS 自身是 "" 无
                    # 合法回退目标，跳过种入 + warn 让 admin 在配置页补齐；其他 key
                    # 的脏 DEFAULTS（如 URL 写错）属配置 bug，必须 fail-fast 抛出
                    # ——首次启动通道与 admin PUT 通道同等对待。
                    if k not in REQUIRED_STRING_KEYS:
                        raise
                    logger.warning(
                        "ConfigStore 跳过种入 %s：DEFAULTS 值 %r 不通过 validate_value，"
                        "需 admin 在配置页补齐后才会落库",
                        k, v,
                    )
                    continue
                session.add(SystemConfig(key=k, value=v))

            if missing:
                await session.commit()
                logger.info("ConfigStore 种入 %d 个默认 key", len(missing))
        # 重读完整缓存
        await self._refresh_cache()

    async def _refresh_cache(self) -> None:
        async with SessionLocal() as session:
            existing = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_B_KEYS)))
            loaded = {row.key: row.value for row in existing.scalars().all()}
        sanitized, reverted = _sanitize_loaded_values(loaded)
        self._cache = sanitized
        # 一次性 banner：admin 部署后立刻看到「哪些 key 被偷偷改回默认」，
        # 避免下次再写同一个错值。WARNING 而非 ERROR：sanitize 是恢复不是失败。
        if reverted:
            logger.warning(
                "ConfigStore 加载时回退 %d 个 key 到 DEFAULTS：%s",
                len(reverted), ", ".join(sorted(reverted)),
            )

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

        ASR 按 type 隔离存储：admin 切换 asr.type 时前端 payload 会把旧
        类型的空字段一并提交——这些空字段不该被写入，也不该触发
        REQUIRED_STRING_KEYS 校验（#177）。运行路径只读激活类型的字
        段，非激活类型的空值留着也只是脏数据。items 里带 asr.type 就
        以 items 为准（admin 正在切换），否则用 cache 兜底。
        """
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        if "asr.type" in items or "asr.type" in self._cache:
            active_asr_type = (
                items.get("asr.type") or self._cache.get("asr.type") or ""
            )
            if active_asr_type:
                items = {
                    k: v
                    for k, v in items.items()
                    if (
                        not k.startswith("asr.")
                        or k == "asr.type"
                        or k.startswith(f"asr.{active_asr_type}.")
                    )
                }

        async with SessionLocal() as session:
            dialect = session.bind.dialect.name if session.bind else "sqlite"
            for key, value in items.items():
                if key not in ALL_B_KEYS:
                    raise ValueError(f"unknown config key: {key}")
                # 敏感字段空值跳过：仅当缓存里已有非空值时跳过（保留旧 API Key，
                # 防 admin 表单"看似保存"实则没改）。api_key 同时属于
                # REQUIRED_STRING_KEYS，若缓存值已为空必须走 validate_value 拦
                # 下空提交，否则首握失败时 admin 看不出是"忘了填"还是"服务挂"。
                if (
                    key in SENSITIVE_KEYS
                    and value == ""
                    and (self._cache.get(key) or "").strip() != ""
                ):
                    continue
                validate_value(key, value)
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
            if (
                key in SENSITIVE_KEYS
                and value == ""
                and (self._cache.get(key) or "").strip() != ""
            ):
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
        "jwt_expire_minutes": int(await s.get("auth.jwt_expire_minutes") or "10080"),
        "allow_registration": (await s.get("auth.allow_registration") or "false") == "true",
        "refresh_token_expire_days": int(await s.get("auth.refresh_token_expire_days") or "30"),
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
    上限钳到 NUMERIC_MAX_VALUE 兜底——validate_value 是写入侧唯一入口，
    但 DB 直改 / 镜像回放 / 未来重构漏调校验时，运行时仍能自保。
    """
    s = get_config_store()
    try:
        v = max(1, int(await s.get("session.max_concurrent") or "10"))
    except (TypeError, ValueError):
        return 10
    return min(v, NUMERIC_MAX_VALUE["session.max_concurrent"])

