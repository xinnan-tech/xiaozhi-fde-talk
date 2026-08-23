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

from fastapi import FastAPI, Request
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.adapters.asr.factory import invalidate as asr_invalidate
from app.adapters.llm.factory import invalidate as llm_invalidate
from app.adapters.ocr.factory import invalidate as ocr_invalidate
from app.core.config_store import get_config_store
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


# dev/test 环境兜底的本地 CORS 来源；prod 不允许任何默认值
_DEV_CORS_DEFAULT = ["http://localhost:5173", "http://127.0.0.1:5173"]


def _resolve_cors_origins(settings) -> list[str]:
    """解析 CORS_ORIGINS：未配置时 dev/test 兜底默认，prod fail-fast。"""
    raw = (settings.cors_origins or "").strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if origins:
        return origins
    if settings.env in ("dev", "test"):
        logger.warning(
            "CORS_ORIGINS 未配置，dev 默认放行 %s。"
            "上线前请在 .env / 环境变量里显式列白名单。",
            _DEV_CORS_DEFAULT,
        )
        return list(_DEV_CORS_DEFAULT)
    raise RuntimeError("CORS_ORIGINS 未配置（上公网必填）")


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
    from app.services.sessions.manager import manager
    from app.services.template.loader import load_templates

    settings = get_settings()
    try:
        await init_db()
    except RuntimeError as e:
        # 配置错误：stderr 单行提示 + SystemExit(2) 立即退出。
        # SystemExit 通过 asyncio Task 抛出后由 main() 沿调用栈向上传；
        # 比 os._exit 友好——单元测试可 catch、IDE debug 不被杀。
        print(f"\n[配置错误] {e}\n", file=sys.stderr, flush=True)
        raise SystemExit(2)

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
    load_templates()

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
        version="1.0.0",
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
    # 显式方法/请求头白名单：通配 "*" 锁定到 RESTful 标准 + 当前路由实际用到的
    # 自定义头（X-Lang 多语请求；X-Request-ID 由中间件生成回传，便于客户端核对）。
    # expose 同步回写 X-Request-ID，否则浏览器 JS 拿不到该响应头，对账失败。
    _ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    _ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Lang", "X-Request-ID"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=_ALLOWED_METHODS,
        allow_headers=_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    # i18n: per-request locale resolution (X-Lang → Accept-Language → DEFAULT).
    from app.core.i18n.middleware import I18nHTTPMiddleware
    app.add_middleware(I18nHTTPMiddleware)

    # gzip 中间件：text 类响应 ≥ 1024 B 自动压缩；4 MB 静态资源 → ~1 MB。
    # 顺序：CORS → I18n → GZip → request_id。
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1024)

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

    @app.exception_handler(I18nError)
    async def _i18n_handler(request: Request, exc: I18nError):
        locale = current_locale()
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.localized(locale=locale), "code": exc.code},
            headers={"Content-Language": locale},
        )

    return app
