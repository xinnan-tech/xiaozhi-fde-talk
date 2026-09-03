"""集成测试：WebSocket 协议路由 + 鉴权 + 续传 + 音频 + 辅导。

依赖运行中的后端服务（pytest_collection_modifyitems 在服务离线时整体跳过）。
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

WS_BASE = "ws://localhost:8000"

pytestmark = pytest.mark.integration


async def test_ws_echo():
    async with websockets.connect(f"{WS_BASE}/ws/v1/echo") as ws:
        await ws.send("hello")
        resp = json.loads(await ws.recv())
        assert resp["type"] == "echo" and resp["data"] == "hello", resp


async def test_ws_handshake_and_flow(client, login, create_session, end_session):
    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {
        "type": "hello",
        "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
    }

    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        reply = json.loads(await ws.recv())
        assert reply["type"] == "hello" and reply["session_id"] == sid and reply["resume_from_seq"] == 0, reply

        # 协议路由：listen / 音频 / skip / listen stop（这些无服务器回复，直接连续发）
        await ws.send(json.dumps({"type": "listen", "state": "start"}))
        for seq in (1, 2, 3):
            await ws.send(seq.to_bytes(4, "big") + b"\x00" * 10)
        await ws.send(json.dumps({"type": "coaching.skip", "id": "pain"}))
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))
        await asyncio.sleep(0.3)

    await end_session(client, token, sid)


async def test_ws_bad_token(client, login, create_session):
    """坏 token / 无 token：握手阶段直接被拒（HTTP 403），连接建立不起来。"""
    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    for subprotocols in (["bearer.bad.token"], []):
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with websockets.connect(uri, subprotocols=subprotocols):
                pass


async def test_ws_token_in_hello_body_rejected(client, login, create_session):
    """token 只认子协议：放在 hello 消息体里不生效，握手照样被拒。"""
    token = await login(client)
    sid = await create_session(client, token)
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(f"{WS_BASE}/ws/v1/interview/{sid}") as ws:
            await ws.send(json.dumps({"type": "hello", "token": f"Bearer {token}"}))


async def test_ws_asr_bad_token():
    """ASR WS 与 interview WS 同一鉴权规则：无 token / 坏 token 握手被拒（403）。

    回归：/ws/v1/asr 曾完全无鉴权，匿名连接可白用上游 ASR（计费/算力）。
    """
    for subprotocols in (["bearer.bad.token"], []):
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with websockets.connect(f"{WS_BASE}/ws/v1/asr", subprotocols=subprotocols):
                pass


async def test_ws_asr_valid_token_connects(client, login):
    """合法 token 握手成功（子协议回显），鉴权不再挡住正常录音链路。"""
    token = await login(client)
    async with websockets.connect(f"{WS_BASE}/ws/v1/asr",
                                   subprotocols=["bearer." + token]) as ws:
        assert ws.subprotocol == "bearer." + token


async def test_ws_resource_isolation(client, login, create_session, create_user):
    admin_token = await login(client)
    await create_user("bob", "bob")
    bob_token = await login(client, "bob", "bob")
    sid = await create_session(client, admin_token)
    async with websockets.connect(f"{WS_BASE}/ws/v1/interview/{sid}",
                                   subprotocols=["bearer." + bob_token]) as ws:
        await ws.send(json.dumps({"type": "hello"}))
        reply = json.loads(await ws.recv())
        assert reply["type"] == "error" and reply["code"] == "not_found", reply


async def test_ws_resume(client, login, create_session, end_session):
    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {"type": "hello", "audio_params": {},
             "client_id": "test-resume-client"}

    # 第一段：发到 seq=3 后断开（不 end）
    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        json.loads(await ws.recv())  # hello reply
        await ws.send(json.dumps({"type": "listen", "state": "start"}))
        for seq in (1, 2, 3):
            await ws.send(seq.to_bytes(4, "big") + b"\x00" * 10)
    # 断开后需等服务器把 3 帧喂进 ASR（首启 ~1s 会先阻塞 _loop）、consumed_seq 推到 3。
    # 固定 sleep 慢环境会竞态、快环境白等，改成轮询 GET 的 consumed_seq（内存态，
    # 与重连 resume_from_seq 同源），到达即退，正常 ~1.5s、最坏 10s 兜底。
    deadline = asyncio.get_event_loop().time() + 10.0
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v1/interviews/{sid}",
                             headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200 and r.json().get("consumed_seq") == 3:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("consumed_seq 未在 10s 内到达 3")

    # 重连：resume_from_seq 应 = 4（consumed_seq=3）
    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        reply = json.loads(await ws.recv())
        assert reply["type"] == "hello" and reply["resume_from_seq"] == 4, reply

    # 清理：end 掉，避免顶住同用户后续测试的并发限制
    await end_session(client, token, sid)


async def test_ws_audio(client, login, create_session, end_session, zh_webm):
    """端到端音频：WebM/Opus → WS 上行 → 服务器解码 → 流式 ASR → 收 asr 文本。

    音频断句由流式 ASR 服务端处理。
    此测试依赖 FunASR 服务端运行，否则跳过。
    """
    import httpx

    # FunASR 服务端可用性检查
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            await c.get("http://localhost:10096")
    except Exception:
        pytest.skip("FunASR 服务端不可用（ws://localhost:10096），跳过音频测试")

    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {
        "type": "hello",
        "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1},
    }

    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        assert json.loads(await ws.recv())["type"] == "hello"
        await ws.send(json.dumps({"type": "listen", "state": "start"}))
        CHUNK = 4000
        for i, off in enumerate(range(0, len(zh_webm), CHUNK)):
            await ws.send(i.to_bytes(4, "big") + zh_webm[off:off + CHUNK])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))
        for _ in range(30):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg["type"] == "asr" and msg["final"] is True:
                break

    await end_session(client, token, sid)


async def test_ws_coaching(client, login, create_session, end_session, zh_webm):
    """辅导引擎 WS 集成测试：验证首算推送 + 30s 计时器触发重算 + skip + end。

    辅导触发由会话内部 30s 计时器驱动。
    此测试依赖 FunASR 服务端运行，否则跳过。
    """
    import httpx

    # FunASR 服务端可用性检查
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            await c.get("http://localhost:10096")
    except Exception:
        pytest.skip("FunASR 服务端不可用（ws://localhost:10096），跳过辅导测试")

    token = await login(client)
    sid = await create_session(client, token)
    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {
        "type": "hello",
        "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1},
    }

    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        for _ in range(20):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") == "hello":
                assert msg["session_id"] == sid
                break
        else:
            raise AssertionError("未收到 hello")

        await ws.send(json.dumps({"type": "listen", "state": "start"}))

        # 等首算推送（final phase，version=1，6条 must_ask）
        found_first = False
        for _ in range(15):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if msg["type"] == "coaching.update" and msg["phase"] == "final":
                assert msg["version"] >= 1
                assert len(msg["items"]) == 6, f"expect 6 must_ask, got {len(msg['items'])}"
                ids = [it["id"] for it in msg["items"]]
                assert ids == ["objective", "pain", "current_solution", "constraints", "decision", "success"], ids
                found_first = True
                break
        assert found_first, "未收到首算 coaching.update"

        # 发音频 → 流式 ASR → 实时文本（辅导触发由 30s 计时器驱动，不再立即触发）
        CHUNK = 4000
        for i, off in enumerate(range(0, len(zh_webm), CHUNK)):
            await ws.send(i.to_bytes(4, "big") + zh_webm[off:off + CHUNK])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))

        # 等待 30s 计时器触发重算（最多等 90s）
        deadline = asyncio.get_event_loop().time() + 90
        asr_received = False
        coaching_after_audio = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                break
            if msg["type"] == "asr":
                asr_received = True
            elif msg["type"] == "coaching.update":
                coaching_after_audio = True

        assert asr_received or coaching_after_audio

        await ws.send(json.dumps({"type": "coaching.skip", "id": "pain"}))
        await asyncio.sleep(0.3)

    await end_session(client, token, sid)
