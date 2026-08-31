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
        # /health 编排器/公网探测：剥 __version__ —— 版本号是侦察信号，
        # 给"已知 X.Y 的某个 CVE 可利用"的攻击者直接送出靶标。
        # 深度诊断（含版本）放 admin 专用端点。
        return {"status": "ok"}

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
            # 不返 __version__：编排器轮询本端点，外网侦察「已知 X.Y 的某个
            # CVE 可利用」攻击者直接拿到靶标——/health 已剥，/ready 同步剥。
            # 深度诊断（含版本）放 admin 专用端点。
            content={"ok": ok, "db": ok},
        )

    if get_settings().env != "prod":
        # ─────────────────────────────────────────────────────────────────
        # ⚠️ 安全警告：本端点仅在 env != "prod" 时挂载。一旦 prod 部署误把
        # ENV 设成 "dev" 或 "test"（_validate_prod 只检查 DB_URL + ASR_WS_URL，
        # 不替 ENV 把关），/ws/v1/echo 0 鉴权直接对外可达。
        # 硬保险：除 prod 不挂载外，连接期再判 ws.client.host，必须是 loopback
        # （127.0.0.1 / ::1）。dev / test 也强制本机——若 ENV=dev 被开放到
        # 0.0.0.0 仍能挡。客户端能伪造 X-Forwarded-For，但 ws.client.host 是 socket
        # 真实对端，X-Forwarded-* 拿不到（HTTP 层概念）。
        # ─────────────────────────────────────────────────────────────────
        @app.websocket("/ws/v1/echo")
        async def ws_echo(ws: WebSocket):
            """最简 WS 回显，仅供联调测试。

            0 鉴权 + 无空闲超时。prod 不挂载；dev/test 还加 IP 锁：仅 loopback。
            """
            client = ws.client.host if ws.client else "unknown"
            # 「testclient」是 httpx.ASGITransport 跑 e2e 时给 ws.client.host
            # 注入的占位字符串（实际是测试进程内部 loopback）；不放到白名单会
            # 把整套 ASGITransport e2e 拒掉。
            if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
                logger.warning("/ws/v1/echo 非 loopback 接入拒绝：%s", client)
                await ws.close(code=1008, reason="loopback only")
                return
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
