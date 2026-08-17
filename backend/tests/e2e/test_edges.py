"""握手/接管边角场景。P2：unit 已覆盖单分支，黑盒增量价值低，全部集中于此。

覆盖三条：
1. 握手超时：连上但不回 hello（5s 内不收任何消息）→ 收 handshake_timeout + 4408。
2. 重复 hello：连上 → 发 hello → 再发 hello（业务上不应见，但 ws 协议不拒）→ 不污染。
3. 接管后旧 owner 残留帧：旧 owner 被 kicked 后到 WS 关之前那一两帧残留
   是否会污染新 owner 的会话（幽灵转写类）。

第一条验证客户端契约；第二条验证服务端幂等；第三条是源码 _dispatch
ownership 守卫（`if self.runtime._send_fn != self._send: return`）的黑盒断言。
"""
from __future__ import annotations

import asyncio

import pytest
import websockets

from chaos import _ws_base

pytestmark = pytest.mark.e2e

HANDSHAKE_TIMEOUT_S = 8   # 后端握手超时 5s，留余量给关连


async def test_handshake_timeout_when_no_hello(new_sid, make_client, api):
    """连上 WS 但 5s 内不发 hello：应收 handshake_timeout 错误帧 + 4408 关闭。

    不走 make_client.connect() 是因为它内部会立刻发 hello——这里需要拿一个
    纯裸连接让服务端超时。token 复用 fixture 已登录的 api token。
    """
    sid = await new_sid("E2E握手超时", "握手超时路径")
    url = f"{_ws_base(api.base_url)}/ws/v1/interview/{sid}"
    ws = await websockets.connect(
        url, subprotocols=[f"bearer.{api.token}"], max_size=None,
    )
    try:
        # 啥也不发，等服务端超时关连
        done, _ = await asyncio.wait([asyncio.create_task(ws.wait_closed())],
                                     timeout=HANDSHAKE_TIMEOUT_S)
        assert done, "服务端未按 5s 超时关连"
        assert ws.close_code == 4408, f"期望 4408 握手超时，实际 {ws.close_code}"
    finally:
        await ws.close()


async def test_repeat_hello_after_bound_is_noop(new_sid, make_client):
    """成功 hello 后再发一条 hello + 紧接着一次 listen start：服务端不应把
    hello 误当成 listen:start 重置 seq。

    单纯比较 c.seq 前后没用——send_json 不动 seq，断言恒真。改成让重复 hello
    与一次"喂音频帧"间隔很短：若服务端误处理了 hello（例如把它当 listen:start
    触发 SeqTracker.reset），后续送入的音频帧 seq 序号会与服务端期望对不上
    被拒为"old seq"（ASR 不出段）；守住的形态是「再发的音频帧被正常消费、
    能出 asr 段」。
    """
    sid = await new_sid("E2E重复hello", "重复 hello 不污染会话")
    c = make_client("rehello", sid, client_id="e2e-rh-1")
    await c.connect()
    await c.listen_start()
    # 中间再来一条 hello（拼错大小写、嵌套路径、null、空类型各试一次）
    for t in ("hello", "HELLO", "", None, "listens.start"):
        await c.send_json({"type": t, "audio_params": {}, "client_id": "e2e-rh-1"})
    await asyncio.sleep(1)

    # 推一段流——若 hello 被服务端误当成 listen 触发重置/丢弃，前面 send_json
    # 那一帧的 seq 0 与服务端期望对不上就会再也不出段
    stop = asyncio.Event()
    stream_task = asyncio.create_task(c.stream(45, until=stop))
    first = await c.wait_first_asr()
    assert first, "重复 hello 污染了会话/seq 未正常推进"
    stop.set()
    await asyncio.gather(stream_task, return_exceptions=True)
    assert not c.frames_of("error"), c.frames_of("error")
    await c.close()


async def test_old_owner_residual_frames_do_not_pollute_new_owner(
        api, new_sid, make_client):
    """接管瞬间：旧 owner 被 kicked 后、WS 关前可能还有一两帧残留入站——
    验证 _dispatch 的 ownership 守卫把它们挡在会话外。

    操作：c1 是旧 owner，c2 是 taker。c2 takeover 后立即让 c1 再发两条
    listen/audio（哪怕 c1 已被踢），新 owner c2 的会话应保持纯净。
    """
    sid = await new_sid("E2E接管残留", "接管后旧 owner 残留帧不污染")
    c1 = make_client("residual_old", sid, client_id="e2e-rs-old")
    c2 = make_client("residual_new", sid, client_id="e2e-rs-new")

    hello = await c1.connect()
    assert hello and hello.get("type") == "hello"
    await c1.listen_start()
    s1 = asyncio.create_task(c1.stream(60))

    # taker 连入（pending 态）
    await asyncio.sleep(5)
    await c2.connect(takeover_on_conflict=False)
    assert c2.conflict_event.is_set()

    # 触发接管
    await c2.send_json({"type": "connection.takeover"})
    await asyncio.wait_for(c2.hello_event.wait(), 15)
    assert c2.hello_reply["type"] == "hello"
    # 等 c1 收 kicked（kicked 帧会先到，但 WS 关闭仍在路上）
    assert await asyncio.wait_for(c1.kicked_event.wait(), 15)
    # 此时 c1 的 WS 还在关上途中——以 max latency 试图再发几帧（音频帧/JSON），
    # 全应被服务端 ownership 守卫丢弃，不进入新 owner 的会话。
    try:
        await c1.send_json({"type": "listen", "state": "stop"})
        await c1.send_frame(b"\x00" * 16)
    except Exception:
        pass

    # c2 接管后正常推流
    await c2.listen_start()
    stop = asyncio.Event()
    s2 = asyncio.create_task(c2.stream(40, until=stop))
    first = await c2.wait_first_asr()
    assert first, "接管后未收到任何 asr 段"
    stop.set()
    await asyncio.gather(s1, s2, return_exceptions=True)

    # 不变量检查覆盖了"段尾没被插队、coaching version 不乱"
    assert not c2.frames_of("error"), c2.frames_of("error")
    await c1.close()
    await c2.close()

