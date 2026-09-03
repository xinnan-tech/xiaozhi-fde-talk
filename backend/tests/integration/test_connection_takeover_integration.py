"""集成测试：同一访谈两端竞争 → 冲突弹窗协议 → 接管 → 被踢。

复现用户场景：A、B 两端开同一个访谈，都点继续。修复前两端 WS 都喂同一个解码器
→ 簇边界错乱 → 都不出字。修复后：不同身份（client_id）的第二个连接收到
connection.conflict（前端据此弹「是否接管」），发 connection.takeover 后踢掉旧 owner
（旧 owner 收 connection.kicked），接管者收到 hello 可正常继续。

依赖运行中的后端（pytest_collection_modifyitems 在服务离线时整体跳过）。
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

WS_BASE = "ws://localhost:8000"

pytestmark = pytest.mark.integration


async def _recv_type(ws, want: str, timeout: float = 6.0) -> bool:
    """在 timeout 内收到指定 type 的消息即返回 True；连接被关也视作「已终态」。"""
    try:
        for _ in range(30):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if msg.get("type") == want:
                return True
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        return False
    return False


async def test_two_clients_same_session_conflict_and_takeover(client, login, create_session, end_session):
    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    subproto = ["bearer." + token]
    helloA = {"type": "hello", "client_id": "client-A"}
    helloB = {"type": "hello", "client_id": "client-B"}

    async with websockets.connect(uri, subprotocols=subproto) as wsA:
        await wsA.send(json.dumps(helloA))
        assert json.loads(await wsA.recv())["type"] == "hello"  # A 成 owner
        # 尽量等 A 首算（coaching）落地，避免与 B 接管的 bind 并发 first_compute
        await _recv_type(wsA, "coaching.update", timeout=4)

        async with websockets.connect(uri, subprotocols=subproto) as wsB:
            await wsB.send(json.dumps(helloB))
            # B 不同身份 → 收到 connection.conflict（而非 hello）
            assert json.loads(await wsB.recv())["type"] == "connection.conflict"

            # B 确认接管
            await wsB.send(json.dumps({"type": "connection.takeover"}))
            assert await _recv_type(wsB, "hello", timeout=6), "B 接管后应收到 hello"

            # A 被踢
            assert await _recv_type(wsA, "connection.kicked", timeout=6), "A 应收到 connection.kicked"

    # 清理：结束会话，释放并发名额
    await end_session(client, token, sid)


async def test_same_client_reconnect_no_conflict(client, login, create_session, end_session):
    """同一身份（client_id 相同）重连不算竞争：先后两个连接都直接收到 hello，无 conflict。"""
    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {"type": "hello", "client_id": "same-client"}

    async with websockets.connect(uri, subprotocols=["bearer." + token]) as wsA:
        await wsA.send(json.dumps(hello))
        assert json.loads(await wsA.recv())["type"] == "hello"

    await end_session(client, token, sid)
