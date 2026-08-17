"""WS 端点挂载（连接层入口）。"""
from __future__ import annotations

from fastapi import FastAPI, WebSocket

from app.transport.websocket.handler import WSHandler


def mount(app: FastAPI) -> None:
    @app.websocket("/ws/v1/interview/{interview_id}")
    async def interview_ws(interview_id: str, ws: WebSocket):
        await WSHandler(ws, interview_id).run()
