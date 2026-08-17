"""统一出站发送：wait_for 超时 + 异常归一化为 False。"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


async def safe_send(send_fn: Callable[[dict], Awaitable[None]], msg: dict, *, timeout: float = 2.0) -> bool:
    try:
        await asyncio.wait_for(send_fn(msg), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning("出站发送超时（%ss）", timeout)
        return False
    except Exception as e:  # noqa: BLE001
        # WARNING 而非 DEBUG：单次 send 失败 → _send_dead=True → WS 关 + 会话 SUSPENDED，
        # 影响可见面，必须让运维在 INFO 级日志看到根因（WebSocketDisconnect / OSError / ...）。
        logger.warning("出站发送失败：%s", e)
        return False
