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
    配置类错误（如缺 APP_ADMIN_PASSWORD）由 init_db 抛 RuntimeError，
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
        # 配置错误：stderr 单行提示 + 立即退出（不走 uvicorn [error] 链路打印 traceback）
        # 用 os._exit 而不是 sys.exit：后者会被 asyncio 转成异常被 starlette traceback 出来
        print(f"\n[配置错误] {e}\n", file=sys.stderr, flush=True)
        os._exit(2)

    # 解析 JWT 密钥：DB → 缺失则自动生成并持久化到 system_config 表
    # prod 无密钥时 secret.resolve() 抛 I18nError(http_status=503)；同样按
    # 配置错误路径走（单行 stderr 提示 + os._exit），避开 uvicorn traceback。
    resolver = JWTSecretResolver(settings, SessionLocal)
    try:
        settings.jwt_secret = await resolver.resolve()
    except I18nError as e:
        print(f"\n[配置错误] {e.localized()}\n", file=sys.stderr, flush=True)
        os._exit(2)

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

    app = FastAPI(title="XiaoZhi FDE Talk", version="1.0.0", lifespan=lifespan)

    from fastapi.middleware.cors import CORSMiddleware
    settings = get_settings()
    origins = _resolve_cors_origins(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # i18n: per-request locale resolution (X-Lang → Accept-Language → DEFAULT).
    from app.core.i18n.middleware import I18nHTTPMiddleware
    app.add_middleware(I18nHTTPMiddleware)

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
