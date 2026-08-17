"""单元测试：end 拆除后通知在线 owner（session.ended 帧 + 4406 关 WS）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.runtime import SessionRuntime


def _runtime(make_state):
    rt = SessionRuntime(make_state())
    rt.engine = MagicMock()
    rt.engine.on_end = AsyncMock()
    rt.pipeline = MagicMock()
    rt.pipeline.flush = AsyncMock()
    rt.pipeline.close = AsyncMock()
    rt._force_flush = AsyncMock()  # 落盘走 DB，与本测试焦点（通知/关连接）无关
    return rt


async def test_end_notifies_and_closes_owner_ws(make_state):
    """end：final 推送之后，向 owner 发 session.ended 并以 4406 关其连接。"""
    rt = _runtime(make_state)
    sent, evicted = [], []
    rt._send_fn = AsyncMock(side_effect=lambda m: sent.append(m))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.end()
    assert any(m.get("type") == "session.ended" for m in sent)
    assert evicted == [(4406, "访谈已结束")]


async def test_end_without_owner_is_noop(make_state):
    """owner 已断开（send_fn/evict_fn 均空）：end 正常完成，不抛不送。"""
    rt = _runtime(make_state)
    await rt.end()  # 不应抛异常
    assert rt._fsm.is_terminated


async def test_end_send_failure_still_closes(make_state):
    """session.ended 帧发送失败（连接半死）：仍执行 evict 关连接。"""
    rt = _runtime(make_state)
    evicted = []
    rt._send_fn = AsyncMock(side_effect=RuntimeError("send dead"))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.end()
    assert evicted == [(4406, "访谈已结束")]
