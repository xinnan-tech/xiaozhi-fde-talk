"""单元测试：SessionRuntime 生命周期铁律（unbind≠end）+ Registry 存活窗口过期销毁。

覆盖：unbind 仅暂停（保留 pipeline/engine/outbound 缓冲，不 drain/close）；
RuntimeRegistry 存活窗口过期 → 调 runtime.end() 真正销毁（不再只 pop）。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.runtime import RuntimeRegistry, SessionRuntime


async def test_unbind_preserves_engine_and_pipeline(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()  # 离线：拦截落盘，避免触碰真实 DB
    rt.engine.on_bind = MagicMock()
    rt.engine.on_unbind = MagicMock()
    rt.pipeline.close = AsyncMock()
    await rt.unbind()
    rt.engine.on_unbind.assert_called_once()
    rt.pipeline.close.assert_not_awaited()  # 铁律：unbind 不关 pipeline
    assert rt.outbound._critical is not None  # 出站缓冲仍在


async def test_registry_expire_calls_end(make_state):
    reg = RuntimeRegistry()
    ended = []
    rt = SessionRuntime(make_state())

    async def fake_end():
        ended.append(True)

    rt.end = fake_end
    reg.park("s1", rt, ttl_s=0.01)
    await asyncio.sleep(0.05)
    assert ended == [True]
