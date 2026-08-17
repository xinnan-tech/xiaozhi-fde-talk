"""裸断连（模拟断网）：宽限窗内重连续上同一条转写流水。"""
from __future__ import annotations

import asyncio

import pytest

from chaos import check_frame_invariants, check_interview_data

pytestmark = pytest.mark.e2e


async def test_raw_disconnect_reconnect_within_grace(api, new_sid, make_client):
    """推流中途裸断（不发 stop）→ 5s 内同 client_id 重连 → 转写 seg_id 跨窗口连续。"""
    sid = await new_sid("E2E断线重连", "验证宽限窗内重连复用会话")
    c1 = make_client("drop", sid, client_id="e2e-rd-1")
    await c1.connect()
    await c1.listen_start()
    await c1.stream(30)
    await c1.raw_disconnect()

    await asyncio.sleep(5)  # 宽限窗（60s）内
    c2 = make_client("resume", sid, client_id="e2e-rd-1")
    hello = await c2.connect()
    assert hello and hello.get("type") == "hello"
    assert not c2.conflict_event.is_set()

    await c2.listen_start()
    await c2.stream(30)
    await c2.listen_stop()

    # 两个连接的帧流合并后仍须满足全部协议不变量（seg_id 全程递增不回退）
    merged = c1.in_frames + c2.in_frames
    assert not check_frame_invariants(merged, "merged"), check_frame_invariants(merged, "merged")

    await asyncio.sleep(10)  # 等尾句收尾 + 落库
    info = await api.get_interview(sid)
    assert info["transcript"], "断线重连后转写为空"
    assert not check_interview_data(info, sid), check_interview_data(info, sid)

    await c2.close()
    await c1.close()
