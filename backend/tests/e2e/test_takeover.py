"""连接竞争（多标签抢同一访谈）：conflict 提示 → takeover 接管 → 旧端被踢 4402。"""
from __future__ import annotations

import asyncio

import pytest

from chaos import check_frame_invariants

pytestmark = pytest.mark.e2e


async def test_takeover_kicks_old_owner(api, new_sid, make_client):
    """第二个标签（不同 client_id）接管后，原 owner 收 kicked 并被 4402 关闭。"""
    sid = await new_sid("E2E抢连接", "验证多标签抢同一会话的接管与踢人")
    c1 = make_client("owner", sid, client_id="e2e-tk-1")
    c2 = make_client("taker", sid, client_id="e2e-tk-2")

    hello = await c1.connect()
    assert hello and hello.get("type") == "hello"
    await c1.listen_start()
    s1 = asyncio.create_task(c1.stream(60))

    # 第二个标签连入：先收到 connection.conflict（提示"是否接管"），拿不到 hello
    await asyncio.sleep(10)
    h2 = await c2.connect(takeover_on_conflict=False)
    assert h2 is None, "存在 owner 时新连接不应直接收到 hello"
    assert c2.conflict_event.is_set()
    conflict = c2.frames_of("connection.conflict")[0]["data"]
    assert "接管" in conflict.get("message", "")

    # pending 期间旧 owner 不受影响：未被踢、无错误帧
    await asyncio.sleep(5)
    assert not c1.kicked_event.is_set(), "pending 未接管不应踢旧 owner"
    assert not c1.frames_of("error")

    # 确认接管：c2 拿到 hello 成为新 owner；c1 收 kicked + 4402
    await c2.send_json({"type": "connection.takeover"})
    await asyncio.wait_for(c2.hello_event.wait(), 15)
    assert c2.hello_reply["type"] == "hello"
    assert await asyncio.wait_for(c1.kicked_event.wait(), 15), "接管后旧 owner 未收到 connection.kicked"
    assert await c1.wait_closed(10)
    assert c1.close_code == 4402, f"期望 4402（被接管踢出），实际 {c1.close_code}"

    # 新 owner 继续推流，会话仍然健康
    await c2.listen_start()
    stop = asyncio.Event()
    s2 = asyncio.create_task(c2.stream(40, until=stop))
    # 等接管后的首段 asr；硬上限兜底，避免死等。
    first = await c2.wait_first_asr()
    assert first, "接管后未收到任何 asr 段（ASR 异常或接管路径坏了）"
    await asyncio.sleep(2)
    assert not c2.frames_of("error")
    assert not check_frame_invariants(c2.in_frames, c2.name)

    code, body = await api.end_interview(sid)
    assert code == 200, body
    # REST end 返回后，终局辅导重算（LLM，设计上限 60s）完成才推 session.ended
    assert await asyncio.wait_for(c2.ended_event.wait(), 70)
    stop.set()
    await asyncio.gather(s1, s2, return_exceptions=True)
    await c1.close()
    await c2.close()


async def test_pending_connection_cannot_hijack_session(new_sid, make_client):
    """pending（未接管）连接发的 listen/音频帧被 ownership 守卫丢弃，不能污染会话。"""
    sid = await new_sid("E2E幽灵帧", "验证 pending 连接的入站帧被忽略")
    c1 = make_client("owner", sid, client_id="e2e-gh-1")
    c2 = make_client("ghost", sid, client_id="e2e-gh-2")

    await c1.connect()
    await c1.listen_start()
    s1 = asyncio.create_task(c1.stream(30))

    await asyncio.sleep(3)
    h2 = await c2.connect()
    assert h2 is None and c2.conflict_event.is_set()

    # pending 端模仿正常客户端发 listen:start + 音频帧
    await c2.listen_start()
    await c2.send_frame(b"\x00" * 800)
    await c2.send_frame(b"\x00" * 800)

    # owner 不受任何影响：未被踢、无错误帧、连接存活
    await asyncio.sleep(5)
    assert not c1.kicked_event.is_set()
    assert not c1.frames_of("error")
    assert not check_frame_invariants(c1.in_frames, c1.name)

    await asyncio.gather(s1, return_exceptions=True)
    await c1.close()
    await c2.close()


async def test_same_client_id_reconnect_is_not_competition(new_sid, make_client):
    """同 client_id（同标签刷新/断网重连）不触发 conflict，直接无缝复用。"""
    sid = await new_sid("E2E重连复用", "验证同身份重连不算竞争")
    c1 = make_client("first", sid, client_id="e2e-rc-1")
    await c1.connect()
    await c1.listen_start()
    await c1.stream(15)
    await c1.raw_disconnect()

    c2 = make_client("reconn", sid, client_id="e2e-rc-1")
    hello = await c2.connect()
    assert hello and hello.get("type") == "hello"
    assert not c2.conflict_event.is_set(), "同 client_id 重连不应收到 connection.conflict"
    await c2.close()
