"""FastAPI 应用入口（composition root）。

app.py 是装配层——把 transport 挂到 app、lifespan 预初始化
persistence/adapters、显式注入 Provider 到 Runtime，是唯一允许"知道所有层"的地方。

HTTP REST（控制平面）+ WebSocket（实时访谈通道）共用单端口。
铁律3：连接池 / 模板等组件在 lifespan 启动时预初始化。
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Any

from fastapi import FastAPI, Request
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.adapters.asr.factory import invalidate as asr_invalidate
from app.adapters.llm.factory import invalidate as llm_invalidate
from app.adapters.ocr.factory import invalidate as ocr_invalidate
from app import __version__
from app.core.config_store import get_config_store
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def _resolve_cors_origins(settings) -> list[str]:
    """解析 CORS_ORIGINS：留空 → ["*"]（开发友好），显式设值 → 白名单（生产安全）。

    留空模式自动放行所有 origin，配合下方 allow_credentials=False 走通：
    鉴权走 Authorization header（JWT，见 transport/http/dependencies.py），
    不依赖 cookie，跨域 cookie 被浏览器禁掉跟鉴权无关——任意 origin 都能调 API。

    上公网前在 .env / 环境变量里显式列白名单（逗号分隔 origin），自动切回严格模式：
    allow_credentials 重新启用，未来若改用 cookie 鉴权也能无缝接上。
    """
    raw = (settings.cors_origins or "").strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if origins:
        return origins
    logger.warning(
        "CORS_ORIGINS 未配置，默认放行所有 origin（开发友好）。"
        "上公网前请在 .env / 环境变量里显式列白名单启用严格模式。"
    )
    return ["*"]


async def _lifespan_startup(app: FastAPI) -> None:
    """lifespan 启动：DB init + ConfigStore warm + JWT 密钥解析 + 清扫僵尸 + 模板加载 + idle watchdog。

    流式 ASR 在 listen:start 时创建连接，不再全局预加载。
    配置类错误（如 alembic 迁移失败）由 init_db 抛 RuntimeError，
    这里捕获后打印一行用户友好提示并 os._exit，避开 uvicorn 的 [error] Traceback 噪音。
    """
    from app.core.i18n.errors import I18nError
    from app.core.secret import JWTSecretResolver
    from app.persistence.bootstrap import init_db, sweep_stale_sessions
    from app.persistence.db import SessionLocal
    from app.services.auth._pwd_ver_clock import seed_from_db_max
    from app.services.sessions.manager import manager
    from app.services.template.loader import warm as warm_templates
    from sqlalchemy import func, select

    from app.persistence.models import User

    settings = get_settings()
    try:
        await init_db()
    except RuntimeError as e:
        # 配置错误：stderr 单行提示 + SystemExit(2) 立即退出。
        # SystemExit 通过 asyncio Task 抛出后由 main() 沿调用栈向上传；
        # 比 os._exit 友好——单元测试可 catch、IDE debug 不被杀。
        print(f"\n[配置错误] {e}\n", file=sys.stderr, flush=True)
        raise SystemExit(2)

    # pwd_ver 写入时钟灌种子：取 DB 中当前最大 password_changed_at 作为 _last。
    # 进程重启后 _last 不再为 0，同秒内首次写严格 > 已落库值——避免「旧进程写
    # 28、新进程同秒写 27」跌穿（base.py:50 判定 N==N 放行，旧 token 不吊销）。
    # 多 worker（WEB_CONCURRENCY>=2）下各 worker 各自 seed，仍有竞态——留给
    # DB 层原子写法跟进，本节仅守「单进程 + 进程重启」场景。
    async with SessionLocal() as db:
        row = (
            await db.execute(select(func.max(User.password_changed_at)))
        ).scalar_one_or_none()
    seed_from_db_max(int(row.timestamp()) if row is not None else None)

    # 解析 JWT 密钥：DB → 缺失则自动生成并持久化到 system_config 表
    # prod 无密钥时 secret.resolve() 抛 I18nError(http_status=503)；同样按
    # 配置错误路径走（单行 stderr 提示 + SystemExit(2)），避开 uvicorn traceback。
    resolver = JWTSecretResolver(settings, SessionLocal)
    try:
        settings.jwt_secret = await resolver.resolve()
    except I18nError as e:
        print(f"\n[配置错误] {e.localized()}\n", file=sys.stderr, flush=True)
        raise SystemExit(2)

    # 配置 KV 预热（含默认值种入 + 内存缓存）
    await get_config_store().warm()
    # provider 缓存订阅 invalidate
    get_config_store().subscribe(llm_invalidate)
    get_config_store().subscribe(asr_invalidate)
    get_config_store().subscribe(ocr_invalidate)

    swept = await sweep_stale_sessions()
    await warm_templates()

    # idle watchdog：会话无活动超过阈值自动转 SUSPENDED
    manager.start_idle_watchdog()

    logger.info(
        "应用已启动（数据库初始化完成，重启时挂起 %d 个进行中的会话，模板已加载，空闲看门狗已启动）",
        swept,
    )


def create_app() -> FastAPI:
    """app factory：装配所有层。"""
    from contextlib import asynccontextmanager

    # i18n: fail-fast on incomplete en-US catalog before constructing the app.
    from app.core.i18n import startup_check
    startup_check.assert_catalog_complete()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _lifespan_startup(app)
        try:
            yield
        finally:
            from app.adapters.llm.factory import shutdown as llm_shutdown
            from app.persistence.db import engine as _engine
            from app.services.sessions.manager import manager
            from app.services.sessions.runtime import registry
            await manager.stop_idle_watchdog()
            runtimes = registry.all_runtimes()
            if runtimes:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            *[r.shutdown_quick() for r in runtimes],
                            return_exceptions=True,
                        ),
                        timeout=10,
                    )
                except asyncio.TimeoutError:
                    logger.warning("优雅关闭超时（10s），强制退出")
            logger.info("关闭完成：已排空 %d 个运行时", len(runtimes))
            try:
                await llm_shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning("shutdown 关闭 LLM 客户端失败：%s", e)
            try:
                from app.adapters.ocr.factory import shutdown as ocr_shutdown
                await ocr_shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning("shutdown 关闭 OCR 客户端失败：%s", e)
            await _engine.dispose()
            logger.info("应用已关闭")

    app = FastAPI(
        title="XiaoZhi FDE Talk",
        version=__version__,
        description=(
            "面向 FDE、产品经理、售前、咨询师等需要频繁做客户访谈的角色："
            "实时 AI 辅导 + 全程转写 + 自动结构化报告。"
        ),
        contact={
            "name": "xinnan-tech",
            "url": "https://github.com/xinnan-tech/xiaozhi-fde-talk/issues",
        },
        license_info={
            "name": "Apache-2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0",
        },
        servers=[{"url": "/", "description": "Current host"}],
        lifespan=lifespan,
        # prod 关闭 Swagger UI / ReDoc / OpenAPI schema：避免把全部 API 形状
        # （含 /api/v1/admin/* 路径与 DTO 结构）暴露给公网。dev/test 保留便于对接。
        docs_url=None if get_settings().env == "prod" else "/docs",
        redoc_url=None if get_settings().env == "prod" else "/redoc",
        openapi_url=None if get_settings().env == "prod" else "/openapi.json",
    )

    from fastapi.middleware.cors import CORSMiddleware
    settings = get_settings()
    origins = _resolve_cors_origins(settings)
    # CORS_ORIGINS 留空时返回 ["*"]，FastAPI 强制要求 * 模式下 allow_credentials=False
    # （否则启动报 ValueError）。本项目鉴权走 Authorization header，cookie 不关键，
    # 留空模式不带 cookie 无影响；显式白名单模式下重新启用 credentials。
    allow_all = origins == ["*"]
    # 显式方法/请求头白名单：通配 "*" 锁定到 RESTful 标准 + 当前路由实际用到的
    # 自定义头（X-Lang 多语请求；X-Request-ID 由中间件生成回传，便于客户端核对）。
    # expose 同步回写 X-Request-ID，否则浏览器 JS 拿不到该响应头，对账失败。
    _ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    _ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Lang", "X-Request-ID"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not allow_all,
        allow_methods=_ALLOWED_METHODS,
        allow_headers=_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    # i18n: per-request locale resolution (X-Lang → Accept-Language → DEFAULT).
    from app.core.i18n.middleware import I18nHTTPMiddleware
    app.add_middleware(I18nHTTPMiddleware)

    # gzip 中间件：text 类响应 ≥ 1024 B 自动压缩；image/* / font / 已压缩格式跳过。
    # 不用 starlette.middleware.gzip.GZipMiddleware：0.41.x 不支持 exclude_content_types
    # 会把所有 ≥1024 B 响应（含 image/png）都压一遍，CPU 白烧还变大。
    # 自实现 CompressibleGZipMiddleware 复刻 starlette 0.42+ 的 DEFAULT_EXCLUDED 语义。
    # 顺序：CORS → I18n → CompressibleGZip → request_id。
    from app.middleware.compressible_gzip import CompressibleGZipMiddleware
    app.add_middleware(CompressibleGZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def request_id_middleware(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response
        finally:
            clear_contextvars()

    # --- HTTP 业务路由（来自 transport/http/routes/）---
    from app.transport.http.routes import router as api_router
    app.include_router(api_router)

    # --- WebSocket 路由（连接层在 transport/websocket/）---
    from app.transport.websocket.server import mount as mount_ws
    mount_ws(app)

    # --- health + echo ---
    from app.transport.health import mount as mount_health
    mount_health(app)

    # --- 前端 SPA 托管（部署模式） ---
    settings = get_settings()
    if settings.serve_frontend:
        from app.transport.static import mount as mount_static
        mount_static(app)

        from app.transport.spa_fallback import mount as mount_spa
        mount_spa(app)

    # i18n: exception handler — for now a no-op (no I18nError raised anywhere).
    # Becomes active in T07-T12 once adapters and routes start adopting.
    from fastapi.responses import JSONResponse
    from app.core.i18n.context import current_locale
    from app.core.i18n.errors import I18nError
    from app.core.i18n.messages import Keys
    from app.core.i18n.translator import t

    @app.exception_handler(I18nError)
    async def _i18n_handler(request: Request, exc: I18nError):
        locale = current_locale()
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.localized(locale=locale), "code": exc.code},
            headers={"Content-Language": locale},
        )

    # pydantic 422：默认 detail 是英文「String should have at least N characters」之类，
    # 直接返回给前端用户看不懂。逐条按 error.type 映射到 i18n key，附带字段名与
    # ctx 里的 min_length / max_length / pattern，让前端照旧按数组解析（loc + msg）。
    #
    # 字段级精细化：username 在 auth endpoint 上有具体 pattern 约束，
    # `string_pattern_mismatch` 通用 key 文案（「格式不正确」）太笼统、不知道
    # 期望什么——落到 username 字段时换用 `auth.username_invalid_format`（已说明
    # 「4-32 位字母、数字、下划线或连字符」）。
    from fastapi.exceptions import RequestValidationError

    _PYDANTIC_TYPE_TO_KEY: dict[str, str] = {
        "missing": Keys.VALIDATION_REQUIRED,
        "string_too_short": Keys.VALIDATION_STRING_TOO_SHORT,
        "string_too_long": Keys.VALIDATION_STRING_TOO_LONG,
        "string_pattern_mismatch": Keys.VALIDATION_STRING_PATTERN_MISMATCH,
        "extra_forbidden": Keys.VALIDATION_EXTRA_FORBIDDEN,
    }
    # 哪些 key 的文案还引用 `{field}`：仅 extra_forbidden（field 指被禁的字段名本身）
    # 与 invalid 兜底（无 field 时也保留——见下面 params 拼装）。
    _KEYS_USE_FIELD: frozenset[str] = frozenset({
        Keys.VALIDATION_EXTRA_FORBIDDEN,
        Keys.VALIDATION_INVALID,
    })
    # 字段级精细化：loc[-1] == "username" + pattern_mismatch → 走具体 auth 文案。
    _FIELD_SPECIFIC_OVERRIDE: dict[tuple[str, str], str] = {
        ("username", "string_pattern_mismatch"): Keys.AUTH_USERNAME_INVALID_FORMAT,
    }

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        locale = current_locale()
        items = []
        for err in exc.errors():
            etype = err.get("type", "")
            loc = err.get("loc") or ()
            field = str(loc[-1]) if loc else ""
            ctx = err.get("ctx") or {}
            key = _FIELD_SPECIFIC_OVERRIDE.get((field, etype)) \
                or _PYDANTIC_TYPE_TO_KEY.get(etype, Keys.VALIDATION_INVALID)
            # 仅当 key 文案里仍用 `{field}` 时才传 field——避免 format 多余占位
            # KeyError。generic validation.* 已统一不带 `{field}`（前端用 `${field}: `
            # 前缀代劳），剩下两个 key 是真有需要。
            params: dict[str, Any] = {}
            if key in _KEYS_USE_FIELD:
                params["field"] = field
            if "min_length" in ctx:
                params["min"] = ctx["min_length"]
            if "max_length" in ctx:
                params["max"] = ctx["max_length"]
            try:
                msg = t(key, locale=locale, **params)
            except Exception:
                msg = err.get("msg", "")
            items.append({"type": etype, "loc": list(loc), "msg": msg})
        return JSONResponse(
            status_code=422,
            content={"detail": items},
            headers={"Content-Language": locale},
        )

    return app
