"""全局并发上限（session.max_concurrent）的黑盒回归。

源码专门防御（on_reconnect 走 _start_lock 后检查 active < limit，否则抛
ConcurrentLimitError），黑盒这道分支没覆盖：用 admin 接口临时把
max_concurrent=1，造两个会话→第一个 suspended→第二个占 active→
第一个重新连应被 concurrent_limit + 4409 拒。

不是"把 3 路堆高"那种压力测，而是单用户造两个 meeting、补这一条源码专门
防御的分支的回归。
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.e2e

GRACE_PERIOD_S = 60   # session.grace_period_s 默认


async def test_resume_rejected_by_max_concurrent(api, new_sid, make_client, restore_max_concurrent):
    """max_concurrent=1 时第二个活跃占满额度；第一个 suspended 尝试恢复应
    在握手阶段被 on_reconnect 拒（concurrent_limit 错误帧 + 4409 关闭）。

    用 restore_max_concurrent 上下文管理器兜底：先读原值、退出 finally 还原
    原值——避免硬编码回填 `10` 在"默认值非 10 / 用例异常 / 进程被杀"场景下
    留下 max_concurrent=1 污染环境。
    """
    async with restore_max_concurrent("1"):
        # 会话 1：推一会断开，等进 suspended
        sid1 = await new_sid("E2E并发-1", "挂起后会话 1")
        c1 = make_client("cc1", sid1, client_id="e2e-cl-1")
        await c1.connect()
        await c1.listen_start()
        await c1.stream(12)
        await c1.close()
        await asyncio.sleep(GRACE_PERIOD_S + 15)
        info1 = await api.get_interview(sid1)
        assert info1["status"] == "suspended", f"suspended 未到：{info1['status']}"

        # 会话 2：占住 active（仍连接推流中，不让进 suspended）
        sid2 = await new_sid("E2E并发-2", "占额度的活跃会话 2")
        c2 = make_client("cc2", sid2, client_id="e2e-cl-2")
        await c2.connect()
        await c2.listen_start()
        await c2.stream(8)
        # 此时全局 active=1 == limit=1；任何新 resume 都得被拒

        # 会话 1 尝试 resume → 应被 concurrent_limit 拒（4409）
        c1b = make_client("cc1b", sid1, client_id="e2e-cl-1")
        await c1b.connect()   # handshake 阶段会触发 on_reconnect
        assert await c1b.wait_closed(10), "恢复连接未被服务端关"
        assert c1b.close_code == 4409, (
            f"顶到 max_concurrent 应被 4409 拒，实际 {c1b.close_code}"
        )
        errs = c1b.frames_of("error")
        assert errs and errs[0]["data"]["code"] == "concurrent_limit", (
            f"错误码应为 concurrent_limit，实际 {errs[0]['data'] if errs else None}"
        )

        await c1b.close()
        await c2.close()
