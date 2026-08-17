"""资源泄漏回归检查：会话结束后不留残留 ASR 连接，RSS 增长有界。

需要用例能访问后端进程本机：设 E2E_BACKEND_PID（后端进程号）；ASR 地址默认
100.79.27.90:10096，可用 E2E_ASR_ADDR 覆盖。建议单独跑：
    E2E_BACKEND_PID=<pid> pytest -m e2e tests/e2e/test_leak.py
"""
from __future__ import annotations

import asyncio

import pytest

from conftest import count_asr_connections, rss_kb

pytestmark = pytest.mark.e2e

SETTLE_SECONDS = 25   # 结束后等待 flush + 报告生成的沉降时间
STREAM_SECONDS = 45   # 保证至少出一段转写


async def _run_session_cycle(api, new_sid, make_client, tag: str):
    """一轮完整会话：建访谈 → 推流 → REST 结束 → 等收尾。"""
    sid = await new_sid(f"E2E泄漏-{tag}", "资源泄漏回归：结束后不留残留连接")
    c = make_client(f"leak-{tag}", sid, client_id=f"e2e-lk-{tag}")
    await c.connect()
    await c.listen_start()
    await c.stream(STREAM_SECONDS)
    code, body = await api.end_interview(sid)
    assert code == 200, body
    await c.close()
    info = await api.get_interview(sid)
    assert info["status"] == "ended"
    assert info["transcript"], "泄漏回归轮次未出转写（音频/ASR 环境异常，结果不可信）"
    await asyncio.sleep(SETTLE_SECONDS)


async def test_no_asr_connection_residual_after_end(api, new_sid, make_client, backend_pid):
    """每轮会话结束后，到 FunASR 的连接数必须回到基线（连接泄漏回归）。

    曾经的缺陷：close() 在 recv_loop 清空内部引用后误判"无连接"跳过 ws.close()，
    底层 TCP 永不释放——每场访谈累积泄漏一条 ASR 连接。
    """
    baseline = count_asr_connections(backend_pid)
    for tag in ("r1", "r2"):
        await _run_session_cycle(api, new_sid, make_client, tag)
        after = count_asr_connections(backend_pid)
        assert after <= baseline, (
            f"第 {tag} 轮结束后残留 ASR 连接 {after} 条（基线 {baseline}）："
            "疑似连接泄漏，检查 provider 的 close 路径是否真正关闭了 WS"
        )


async def test_rss_growth_bounded_across_rounds(api, new_sid, make_client, backend_pid,
                                          rss_budget_kb):
    """连续 3 轮会话后，后端 RSS 增长应有界（第 1 轮为预热，不计增长）。

    Python 的内存池不会把内存全还给 OS，RSS 不回落是正常的；判泄漏看的是
    "每轮持续抬升" 的棘轮效应。此断言只拦灾难级泄漏（每轮几十 MB 级），
    小额泄漏靠上面的残留连接检查兜底。

    阈值由 --rss-budget-kb 注入（默认 30MB）。小并发部署 30MB 即足够拦灾难；
    大并发部署可放宽（--rss-budget-kb=102400）。
    """
    samples = []
    for tag in ("warm", "r1", "r2"):
        await _run_session_cycle(api, new_sid, make_client, tag)
        samples.append(rss_kb(backend_pid))
        print(f"[rss] 第 {tag} 轮结束后 RSS = {samples[-1] / 1024:.1f} MB")

    growth = samples[2] - samples[1]
    assert growth < rss_budget_kb, (
        f"两轮会话 RSS 增长 {growth / 1024:.1f} MB（{samples[1] / 1024:.1f}"
        f"→{samples[2] / 1024:.1f} MB）超过预算 {rss_budget_kb / 1024:.1f} MB："
        "疑似每轮泄漏，建议 tracemalloc 排查"
    )
