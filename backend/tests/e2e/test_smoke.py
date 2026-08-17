"""冒烟主链路：连接 → 推流 → 出转写 → REST 结束 → 会话落 ended。"""
from __future__ import annotations

import asyncio

import pytest

from chaos import check_frame_invariants, check_interview_data

pytestmark = pytest.mark.e2e


async def test_stream_then_rest_end(api, new_sid, make_client):
    """全流程：hello 握手、推流出 asr 段、中途 REST 结束收到 session.ended + 4406。"""
    sid = await new_sid("E2E冒烟", "验证全链路：推流出转写后 REST 结束")
    c = make_client("smoke", sid, client_id="e2e-smoke-1")

    hello = await c.connect()
    assert hello and hello.get("type") == "hello"
    await c.listen_start()

    stop = asyncio.Event()
    stream_task = asyncio.create_task(c.stream(90, until=stop))
    # 等首段 asr；硬上限 ASR_DEADLINE_S，ASR 挂了不挂死整个 runner。
    # 比硬编码 sleep 50s 更稳：首段到了立刻进入下一步。
    first = await c.wait_first_asr()
    assert first, "推流上限内未收到任何 asr 段（ASR 异常或音频前导太久）"
    # 顺手再给一会儿，让结构不变量有更多帧可查
    await asyncio.sleep(3)
    assert not check_frame_invariants(c.in_frames, c.name)

    code, body = await api.end_interview(sid)
    assert code == 200, body

    # 终算 LLM 上限 60s（设计约定），session.ended 要等 final 清单推送完才发
    assert await asyncio.wait_for(c.ended_event.wait(), 70), "REST 结束后未收到 session.ended"
    assert await c.wait_closed(15), "REST 结束后 WS 未被服务端关闭"
    assert c.close_code == 4406, f"期望 4406（会话结束），实际 {c.close_code}"
    stop.set()
    await asyncio.gather(stream_task, return_exceptions=True)

    await asyncio.sleep(15)  # 等 final 清单重算 + 落库
    info = await api.get_interview(sid)
    assert info["status"] == "ended"
    assert info["transcript"], "结束后转写为空"
    assert info["items"], "结束后 coaching 清单为空"
    assert not check_interview_data(info, sid), check_interview_data(info, sid)

    await c.close()


async def test_connect_to_ended_session_gets_4406(api, new_sid, make_client):
    """访谈结束后再连 WS：应收到 session_ended 错误帧并被 4406 关闭。"""
    sid = await new_sid("E2E已结束", "验证结束后拒绝连接")
    code, _ = await api.end_interview(sid)
    assert code == 200

    c = make_client("ended_conn", sid, client_id="e2e-ended-1")
    await c.connect()  # hello 后会话已 ended，服务端走错误分支而非回 hello
    assert await c.wait_closed(10)
    assert c.close_code == 4406
    errs = c.frames_of("error")
    assert errs and errs[0]["data"]["code"] == "session_ended"
