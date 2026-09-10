"""前端 SPA 托管（开发可关闭，部署默认开启）。

Docker 镜像中 /app/static 由前端 dist 注入；dev 模式下可设 SERVE_FRONTEND=false
让前端走 pnpm dev，后端仅作为 API。

子路径部署（SUBPATH=/xiaozhi-fde-talk）：
- 浏览器 /xiaozhi-fde-talk/ → 命中 index.html
- 浏览器 /xiaozhi-fde-talk/static/js/xxx.js → 命中 backend/static/static/js/xxx.js
- 浏览器 /xiaozhi-fde-talk/api/... → 透传给业务路由（APIRouter 已带 SUBPATH 前缀）
- 浏览器 /xiaozhi-fde-talk/ws/... → 透传给 WS 路由
- 浏览器 /xiaozhi-fde-talk/platform-config.json → 命中文件
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


# 这些前缀不会被 StaticFiles 接管，必须透传给业务路由
_PASSTHROUGH_PREFIXES = ("/api/", "/ws/", "/health", "/docs", "/openapi.json", "/redoc")


class _SubpathStripMiddleware:
    """ASGI middleware：剥掉请求路径中的 SUBPATH 前缀，命中文件的由 StaticFiles 接管，
    否则透传给业务 app。add_middleware LIFO 语义要求这是最后一个 add 的 middleware。"""

    def __init__(self, app, subpath: str, static_app):
        self.app = app
        self.static_app = static_app
        self.subpath = (subpath or "").rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.subpath:
            return await self.app(scope, receive, send)

        path = scope["path"]
        if not path.startswith(self.subpath):
            return await self.app(scope, receive, send)

        stripped = path[len(self.subpath):] or "/"
        if stripped.startswith(_PASSTHROUGH_PREFIXES):
            return await self.app(scope, receive, send)

        scope["path"] = stripped
        scope["raw_path"] = stripped.encode("utf-8")
        return await self.static_app(scope, receive, send)


def mount(app: FastAPI, subpath: str = "") -> None:
    static_dir = Path(__file__).resolve().parents[2] / "static"
    if not static_dir.is_dir():
        return

    if not subpath:
        # SUBPATH 为空时直接挂 /，不走中间件；否则 /static 与 /platform-config.json
        # 会被 spa_fallback 兜底回 HTML，前端拿 HTML 当 JS/JSON 解析，整站白屏
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
        return

    static_app = StaticFiles(directory=str(static_dir), html=True)
    # add_middleware LIFO 顺序：最后一个 add 的最外层。其他 middleware 在 app.py 之前
    # 已 add（CORS、request-id 等），这里 add 的会跑在最外层——这正是我们想要的：
    # 请求一进来就剥前缀，然后再走 CORS / request-id / 业务路由。
    app.add_middleware(_SubpathStripMiddleware, subpath=subpath, static_app=static_app)
