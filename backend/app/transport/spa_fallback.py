"""SPA 路由兜底：把非 /api/ /health /ws 的 GET 请求返回 index.html。

仅在 SERVE_FRONTEND=true 时启用。开发模式（SERVE_FRONTEND=false）不挂载。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

EXCLUDE_PREFIXES = ("/api/", "/health", "/ws", "/docs", "/openapi.json")


def mount(app: FastAPI) -> None:
    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc):
        if request.method == "GET" and not request.url.path.startswith(EXCLUDE_PREFIXES):
            index = STATIC_DIR / "index.html"
            if index.exists():
                return FileResponse(index)
        return JSONResponse({"detail": "Not Found"}, status_code=404)