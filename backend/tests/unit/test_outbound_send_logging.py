"""outbound send 失败必须 WARNING 级可见：单次失败 → _send_dead → 会话 SUSPENDED。"""
from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.outbound_send import safe_send


@pytest.mark.asyncio
async def test_exception_logged_at_warning(caplog: pytest.LogCaptureFixture):
    """任意 Exception → WARNING 级日志（不再吞在 DEBUG）。"""
    async def _failing(_m):
        raise ConnectionResetError("simulated FE drop")

    with caplog.at_level(logging.WARNING, logger="app.core.outbound_send"):
        ok = await safe_send(_failing, {"type": "x"})

    assert ok is False
    assert any(
        rec.levelno == logging.WARNING and "出站发送失败" in rec.message
        for rec in caplog.records
    ), f"expected WARNING about send failure, got {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_timeout_still_warning(caplog: pytest.LogCaptureFixture):
    """2s 超时仍 WARNING（之前就是 WARNING，本次修改不动）。"""
    async def _slow(_m):
        await asyncio.sleep(5)
        return None

    safe_send._huh = None  # 防止 lint
    # safe_send 默认 timeout=2.0 走 asyncio.wait_for → TimeoutError
    with caplog.at_level(logging.WARNING, logger="app.core.outbound_send"):
        ok = await safe_send(_slow, {"type": "x"})

    assert ok is False
    assert any(
        "出站发送超时" in rec.message for rec in caplog.records
    )