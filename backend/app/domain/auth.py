"""鉴权领域模型。

WS/HTTP 复用同一 CurrentUser 类型，不依赖 fastapi。
"""
from __future__ import annotations

from pydantic import BaseModel


class CurrentUser(BaseModel):
    """解析 token 后的当前用户上下文（协议无关）。"""
    user_id: str
    username: str = ""
    role: str = "user"
