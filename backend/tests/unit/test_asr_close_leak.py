"""单元测试：close() 必须真正关闭 WS，即便 recv_loop 的 finally 先清了 self._ws。

stop_stream 的 wait_for(recv_task, 5) 超时取消 recv_loop，其 finally 置
self._ws=None；close() 若之后才读 self._ws 会跳过 ws.close()，底层 TCP
连接永久滞留（每会话泄漏一条到 ASR 服务端的连接）。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.adapters.asr.funasr_server import FunASRServerProvider


def _provider_with_hung_ws() -> tuple[FunASRServerProvider, MagicMock]:
    """构造带假 WS 的 provider：recv 挂起直到被取消（模拟 FunASR 不回 close）。"""
    prov = FunASRServerProvider()
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()

    async def _hang() -> None:
        await asyncio.sleep(3600)

    ws.recv = AsyncMock(side_effect=_hang)
    prov._ws = ws
    return prov, ws


async def test_close_closes_ws_even_if_recv_finalizer_clears_it():
    """recv_loop 的 finally 置 self._ws=None 后，close 仍必须调用 ws.close()。"""
    prov, ws = _provider_with_hung_ws()
    prov._recv_task = asyncio.create_task(prov._recv_loop())
    await asyncio.sleep(0)  # 让 recv_loop 进入挂起的 recv()

    await prov.close()

    ws.close.assert_awaited_once()
    assert prov._ws is None
    assert not prov._is_stopping


async def test_close_without_recv_task_still_closes():
    """无 recv 任务（start_stream 刚失败等场景）：close 直接关 WS。"""
    prov, ws = _provider_with_hung_ws()
    await prov.close()
    ws.close.assert_awaited_once()
    assert prov._ws is None


async def test_close_after_external_stop_stream_still_closes():
    """外部先单独 stop_stream（pipeline.flush 的序列）后再 close：句柄不得丢。

    stop_stream 的 wait_for(recv_task, 5) 超时取消 recv_loop，其 finally 若把
    self._ws 置 None，close() 抓局部引用时拿到的已是 None → ws.close() 被跳过
    → 底层 TCP 永久滞留（每会话泄漏一条到 ASR 的连接）。recv_loop 结束只标记
    连接不可用，句柄必须保留到 close() 真正关闭它。
    """
    prov, ws = _provider_with_hung_ws()
    prov._recv_task = asyncio.create_task(prov._recv_loop())
    await asyncio.sleep(0)  # 让 recv_loop 进入挂起的 recv()

    await prov.stop_stream()  # 外部先行 stop
    await prov.close()

    ws.close.assert_awaited_once()
    assert prov._ws is None
