"""/health + /ws/v1/echo 联调测试端点。"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app import __version__
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def mount(app: FastAPI) -> None:
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    async def ready():
        from starlette.responses import JSONResponse
        from sqlalchemy import text

        from app.persistence.db import engine

        # 探针必须轻量：编排器周期轮询本端点，绝不能挂真实 LLM/ASR 调用
        # （烧额度 + 占 ASR 并发 + 失败路径向未认证方回显 provider 细节）。
        # 深度诊断在 admin 专用的 POST /api/v1/diagnostics。
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"ok": ok, "db": ok, "version": __version__},
        )

    if get_settings().env != "prod":
        @app.websocket("/ws/v1/echo")
        async def ws_echo(ws: WebSocket):
            """最简 WS 回显，仅供联调测试。

            零鉴权且无空闲超时，连接可被无限挂住——prod 不挂载本端点。
            """
            await ws.accept()
            try:
                while True:
                    try:
                        data = await ws.receive_text()
                        try:
                            parsed = json.loads(data)
                            await ws.send_json({"type": "echo", "original": parsed})
                        except json.JSONDecodeError:
                            await ws.send_json({"type": "echo", "data": data, "protocol": "ws"})
                    except WebSocketDisconnect:
                        break
            except Exception as e:  # noqa: BLE001
                logger.error("WebSocket 回显测试异常：%s", e)
