"""runtime 低电平回调 → audio.low_level 帧（提示性帧，不关连接、不进重放缓冲）。"""
from __future__ import annotations

from unittest.mock import AsyncMock

from app.adapters.asr.level_monitor import LevelReading
from app.services.sessions.runtime import SessionRuntime


async def test_on_low_level_sends_frame(make_state):
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    await rt._on_low_level(LevelReading(-57.3, -82.1, 24.8))
    rt._send_fn.assert_awaited_once()
    assert rt.outbound.critical_for_replay() == []   # 非 critical：断连重连不重放过期提示
    frame = rt._send_fn.call_args.args[0]
    assert frame["type"] == "audio.low_level"
    assert frame["dbfs"] == -57.3
    assert "麦克风" in frame["message"]
