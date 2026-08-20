"""集成测试：MVP 全流程验收（Phase 1-8）。

建访谈 → WS → 音频转写 → 辅导重算 → 结束 → 报告生成 → 导出。
依赖运行中的后端服务（pytest_collection_modifyitems 在服务离线时整体跳过）。
注：音频测试依赖 FunASR 服务端运行，否则跳过。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets

WS_BASE = "ws://localhost:8000"

pytestmark = pytest.mark.integration


async def test_full_flow(client, login, create_session, end_session, zh_webm):
    """全流程验收：首算 + 音频 + 30s 计时器重算 + 报告生成 + 导出。"""
    import httpx

    # FunASR 服务端可用性检查
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            await c.get("http://localhost:10096")
    except Exception:
        pytest.skip("FunASR 服务端不可用（ws://localhost:10096），跳过音频流程测试")

    token = await login(client)
    sid = await create_session(client, token)

    uri = f"{WS_BASE}/ws/v1/interview/{sid}"
    hello = {
        "type": "hello",
        "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1},
    }

    async with websockets.connect(uri, subprotocols=["bearer." + token]) as ws:
        await ws.send(json.dumps(hello))
        # 等 hello（跳过可能先到的 first_compute coaching）
        for _ in range(15):
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if m.get("type") == "hello":
                break
        else:
            raise AssertionError("未收到 hello")

        await ws.send(json.dumps({"type": "listen", "state": "start"}))
        for i, off in enumerate(range(0, len(zh_webm), 4000)):
            await ws.send(i.to_bytes(4, "big") + zh_webm[off:off + 4000])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "listen", "state": "stop"}))

        # 收集 asr + 辅导重算 final（version≥2，30s 计时器触发）
        seen_asr = False
        recompute_v = None
        deadline = asyncio.get_event_loop().time() + 90
        while (not seen_asr or recompute_v is None) and asyncio.get_event_loop().time() < deadline:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            except asyncio.TimeoutError:
                break
            if m["type"] == "asr":
                seen_asr = True
            elif m["type"] == "coaching.update" and m.get("phase") == "final" and m.get("version", 0) >= 2:
                recompute_v = m["version"]
        assert seen_asr, "未收到 asr"
        assert recompute_v is not None, "未收到辅导重算"

    await end_session(client, token, sid)

    # 报告生成 + 导出（大模型生成报告耗时较长，单独用 60s 超时客户端）
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60) as c:
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get(f"/api/v1/interviews/{sid}/report", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "ready", r.text
        md = r.json()["content_md"]
        # 报告骨架应至少保留一个模板里的 heading——直接从 templates/pm.json 抽
        # headings，不硬编码中文字串。i18n directive / LLM 输出模板都可能微调标题
        # 字面，但骨架结构（h1 + 多个 h2）必须保留。
        tpl_doc = json.loads(
            (Path(__file__).resolve().parents[2] / "templates" / "pm.json").read_text(
                encoding="utf-8"
            )
        )["doc"]
        headings = [
            line.lstrip("# ").strip()
            for line in tpl_doc.splitlines()
            if line.startswith("# ") or line.startswith("## ")
        ]
        assert any(h_ in md for h_ in headings), (
            f"报告缺骨架；模板 headings={headings}; 报告前 200 字={md[:200]!r}"
        )
        for fmt in ("md", "html", "word"):
            r = await c.post(f"/api/v1/interviews/{sid}/export?format={fmt}", headers=h)
            assert r.status_code == 200 and len(r.content) > 0, f"导出 {fmt} 失败: {r.status_code}"
