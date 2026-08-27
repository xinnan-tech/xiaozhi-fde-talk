"""报告导出走 asyncio.to_thread，不在事件循环线程执行。

慢导出（markdown/bleach/docx）是纯 CPU/同步 IO，若在路由里同步调用，
会占住事件循环线程、冻住所有并发连接。路由必须用 asyncio.to_thread 把
export offload 到工作线程。

判定方式：在 export 内捕获 threading.current_thread()，断言它不是事件循环
所在的 main thread。同步调用 → main thread（红）；to_thread → 工作线程（绿）。
避免计时竞态。
"""
from __future__ import annotations

import threading
import time

import pytest

from app.transport.http.routes import reports as reports_route


@pytest.mark.asyncio
async def test_export_route_offloads_export_to_thread(monkeypatch):
    """导出路由必须把 export offload 到工作线程。"""
    # 绕开归属校验与报告生成（本测试只关心 export 的执行线程）
    async def _noop(*args, **kwargs):
        return None

    async def _ready(*args, **kwargs):
        return ("ready", "# 报告\n\n正文")

    monkeypatch.setattr(reports_route, "_own_session_or_404", _noop)
    monkeypatch.setattr(reports_route, "get_or_generate", _ready)

    main_thread = threading.main_thread()
    seen_thread: list[threading.Thread] = []

    def slow_export(md, fmt):
        # time.sleep 占住调用线程：若在事件循环线程，则冻住整个循环
        seen_thread.append(threading.current_thread())
        time.sleep(0.03)
        return md.encode("utf-8"), "text/markdown; charset=utf-8"

    monkeypatch.setattr(reports_route, "export_report", slow_export)

    resp = await reports_route.export_interview_report("sess-1", "md", user=object())

    assert resp.status_code == 200
    assert seen_thread, "export 未被调用"
    assert seen_thread[0] is not main_thread, (
        "export 在事件循环线程执行——路由没有用 asyncio.to_thread offload，会阻塞循环"
    )
