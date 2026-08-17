from __future__ import annotations

import asyncio

from app.core.outbound_send import safe_send


async def test_safe_send_success():
    async def send(m):
        return None

    assert await safe_send(send, {"x": 1}) is True


async def test_safe_send_timeout_returns_false():
    async def slow(m):
        await asyncio.sleep(5)

    assert await safe_send(slow, {"x": 1}, timeout=0.05) is False


async def test_safe_send_exception_returns_false():
    async def boom(m):
        raise RuntimeError("ws closed")

    assert await safe_send(boom, {"x": 1}) is False
