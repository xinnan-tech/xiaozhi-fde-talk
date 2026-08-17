"""前端 SPA 托管（开发可关闭，部署默认开启）。

Docker 镜像中 /app/static 由前端 dist 注入；dev 模式下可设 SERVE_FRONTEND=false
让前端走 pnpm dev，后端仅作为 API。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount(app: FastAPI) -> None:
    # 后端服务根（backend/）
    static_dir = Path(__file__).resolve().parents[2] / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
