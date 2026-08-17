"""压力与暴力输入：并发会话 / 麦克风开关循环 / 非法帧与错误握手。"""
from __future__ import annotations

import asyncio

import pytest

from chaos import check_frame_invariants, check_interview_data

pytestmark = pytest.mark.e2e


async def test_three_concurrent_sessions(api, new_sid, make_client):
    """3 个访谈会话同时推流：互不串扰、各自出转写、结构不变量全部成立。"""
    clients = []
    for i in range(3):
        sid = await new_sid(f"E2E并发{i + 1}", "并发压力：3 路访谈同时推流")
        c = make_client(f"conc{i + 1}", sid, client_id=f"e2e-cc-{i + 1}")
        hello = await c.connect()
        assert hello and hello.get("type") == "hello"
        await c.listen_start()
        clients.append(c)

    await asyncio.gather(*(c.stream(90) for c in clients))

    for c in clients:
        assert c.frames_of("asr"), f"{c.name}: 90s 推流未收到任何 asr 段"
        assert not check_frame_invariants(c.in_frames, c.name), check_frame_invariants(c.in_frames, c.name)

    await asyncio.gather(*(c.close() for c in clients))
    await asyncio.sleep(8)
    for c in clients:
        info = await api.get_interview(c.sid)
        assert info["transcript"], f"{c.name}: 会话转写为空"
        assert not check_interview_data(info, c.sid), check_interview_data(info, c.sid)


async def test_listen_toggle_cycles(api, new_sid, make_client):
    """麦克风开关循环：listen stop/start × 3，逐轮出段、解码器重置不丢段。"""
    sid = await new_sid("E2E麦克风循环", "开关循环下的解码器重置与尾句收尾")
    c = make_client("toggle", sid, client_id="e2e-tg-1")
    await c.connect()

    prev_segs = 0
    # 音频前 12s 为静音/低语，每轮须 ≥30s 才保证有足够的成句语音
    for i, dur in enumerate((40, 30, 40)):
        await c.listen_start()
        await c.stream(dur)
        await c.listen_stop()
        await asyncio.sleep(8)  # 大于 stop 的 5s drain，确保收尾完成再开下一轮
        segs = len([f for f in c.frames_of("asr")
                    if f["data"].get("seg_id")])
        assert segs > prev_segs, f"第 {i + 1} 轮（{dur}s）推流后转写段数未增长（{segs}）"
        prev_segs = segs
        assert not c.frames_of("error")

    await asyncio.sleep(10)
    info = await api.get_interview(sid)
    assert len(info["transcript"]) >= prev_segs, "落库段数少于 WS 推送的 asr 段数"
    assert not check_interview_data(info, sid), check_interview_data(info, sid)
    await c.close()


# ---- 暴力输入：非法帧/错误握手不应拖垮服务，且给前端明确错误码 ----


async def test_oversized_frame_rejected(new_sid, make_client):
    """>64KB 的音频帧：收到 frame_too_large 错误帧并被 4410 关闭。"""
    sid = await new_sid("E2E超大帧", "验证单帧 64KB 上限")
    c = make_client("big", sid, client_id="e2e-big-1")
    await c.connect()
    await c.send_frame(b"\x00" * (64 * 1024 + 1))
    assert await c.wait_closed(10)
    assert c.close_code == 4410
    errs = c.frames_of("error")
    assert errs and errs[0]["data"]["code"] == "frame_too_large"


async def test_invalid_json_rejected(new_sid, make_client):
    """非 JSON 文本帧：收到 bad_json 错误帧并被关闭。"""
    sid = await new_sid("E2E坏JSON", "验证非法文本帧处理")
    c = make_client("badjson", sid, client_id="e2e-bj-1")
    await c.connect()
    await c.send_raw("{not json")
    assert await c.wait_closed(10)
    errs = c.frames_of("error")
    assert errs and errs[0]["data"]["code"] == "bad_json"


async def test_unknown_message_type_does_not_pollute_session(new_sid, make_client):
    """未知消息类型只记警告：连接保持存活，后续整轮 listen/stream 正常出转写。

    覆盖更彻底：发未知帧后走完 listen:start → 推流 → 收到首段 asr → listen:stop，
    验证非法帧不污染会话状态机。原 3s 测试只验了 listen_start/stop，不验出段。
    """
    sid = await new_sid("E2E未知类型", "验证未知消息类型不污染会话")
    c = make_client("unknown", sid, client_id="e2e-uk-1")
    await c.connect()

    # 阶段 1：发几个未知类型（拼写错误、嵌套超长路径都试一下）
    for t in ("totally.unknown.type", "Coaching.SKIP", "", None):
        await c.send_json({"type": t, "foo": "bar"})

    # 阶段 2：正常链路 — listen:start → 推流 → 收到首段 asr → listen:stop
    await c.listen_start()
    stop = asyncio.Event()
    stream_task = asyncio.create_task(c.stream(60, until=stop))
    first = await c.wait_first_asr()
    assert first, "未知帧污染了会话，正常推流没收到任何 asr 段"
    # 等几帧再停
    await asyncio.sleep(2)
    await c.listen_stop()
    stop.set()
    await asyncio.gather(stream_task, return_exceptions=True)

    assert not c.frames_of("error"), c.frames_of("error")
    assert not check_frame_invariants(c.in_frames, c.name), check_frame_invariants(c.in_frames, c.name)
    await c.close()


async def test_hello_with_bad_token_rejected(new_sid, make_client):
    """token 非法：握手阶段直接被拒（HTTP 401/403），WS 升级失败。

    用裸 httpx 直接断言 HTTP 状态码，不依赖 websockets 库把 HTTP 4xx 升级成
    InvalidStatus——客户端库实现语义变了用例不应跟随。断言 HTTP 层语义就够了。
    """
    import httpx as _httpx
    from chaos import _ws_base as _to_ws
    from conftest import BASE_URL

    sid = await new_sid("E2E坏token", "鉴权失败路径")
    url = f"{_to_ws(BASE_URL)}/ws/v1/interview/{sid}"
    async with _httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "bearer.not-a-jwt",
        })
    assert r.status_code in (401, 403), f"坏 token 应被 401/403 拒，实际 {r.status_code}"
