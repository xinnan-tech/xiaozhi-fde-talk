"""Repository 基础协议。

Repository 抽象：services 层只依赖此协议，不依赖 ORM/SessionLocal。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


class AsyncRepository(Protocol):
    """异步 Repository 协议（结构化类型，实现者无需显式继承）。"""

    async def get(self, *args: Any, **kwargs: Any) -> Optional[Any]: ...
    async def save(self, *args: Any, **kwargs: Any) -> None: ...
