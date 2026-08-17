"""访谈过程操作：忽略/跳过清单项、暂停（断开自动挂起）与继续（重连恢复）、报告生成。

暂停没有显式按钮接口：业务语义是断开 WS 后过 grace_period_s（默认 60s）自动转
suspended，继续 = 重新连接（SUSPENDED→IN_PROGRESS）。报告在 REST end 后按需惰性生成。
"""
from __future__ import annotations

import asyncio
import re

import pytest

from chaos import check_frame_invariants, check_interview_data

pytestmark = pytest.mark.e2e

GRACE_PERIOD_S = 60   # session.grace_period_s 默认值：断开到自动挂起的窗口
IDLE_TIMEOUT_S = 120  # session.idle_timeout_s 默认值：连接在线但无活动的挂起阈值


async def test_idle_suspend_notifies_suspended(api, new_sid, make_client):
    """连接保持但长时间无活动：应发 session.suspended + 4403（可继续），
    而不是 session.ended + 4406（只读）——挂起语义与 DB 落的 suspended 一致。"""
    sid = await new_sid("E2E空闲挂起", "操作测试：在线但无活动的挂起通知语义")
    c = make_client("idle", sid, client_id="e2e-id-1")
    await c.connect()
    await c.listen_start()
    await c.stream(15)

    # 静默保持连接：idle_timeout 120s + 检查间隔 30s，挂起应在此窗口内触发
    await asyncio.wait_for(c.closed_event.wait(), IDLE_TIMEOUT_S + 60)
    assert c.close_code == 4403, f"挂起关闭码应为 4403，实际 {c.close_code}"
    assert not c.frames_of("session.ended"), "挂起不应发 session.ended"
    assert c.frames_of("session.suspended"), "挂起应发 session.suspended"

    await asyncio.sleep(5)
    info = await api.get_interview(sid)
    assert info["status"] == "suspended", f"挂起后状态应为 suspended：{info['status']}"


async def test_rest_end_after_disconnect_stays_ended(api, new_sid, make_client):
    """断开（grace 过后 runtime 仍寄存）再 REST end：终态不得被寄存 runtime 的
    旧快照回写「复活」为 suspended。"""
    sid = await new_sid("E2E终态粘性", "回归：REST end 后落库必须是 ended")
    c = make_client("revive", sid, client_id="e2e-rv-1")
    await c.connect()
    await c.listen_start()
    await c.stream(15)
    await c.close()

    await asyncio.sleep(GRACE_PERIOD_S + 10)  # 过 grace：suspended 落库，runtime 寄存中
    info = await api.get_interview(sid)
    assert info["status"] == "suspended"

    code, _ = await api.end_interview(sid)
    assert code == 200
    info = await api.get_interview(sid)
    assert info["status"] == "ended", "end 即刻应为 ended"

    # 后台拆除（含终局重算 LLM ≤60s）完成后，ended 不得被旧快照回退
    await asyncio.sleep(75)
    info = await api.get_interview(sid)
    assert info["status"] == "ended", f"终态被回写为 {info['status']}（复活）"


def _latest_items(c) -> dict[str, str]:
    """最近一帧带 items 的 coaching.update 里各 item 的状态（id → status）。

    跳过重算中间态（recomputing 阶段可能推 items 为空的帧）。
    """
    for r in reversed(c.records):
        if r["dir"] != "in" or r["kind"] != "coaching.update":
            continue
        items = r["data"].get("items")
        if items:
            return {it["id"]: it.get("status", "?") for it in items}
    return {}


async def test_skip_and_ignore_coaching_items(api, new_sid, make_client):
    """访谈中忽略/跳过清单项：下一轮重算里状态翻为 ignored/skipped 且不再回跳。"""
    sid = await new_sid("E2E忽略跳过", "操作测试：忽略与跳过清单项")
    c = make_client("skipign", sid, client_id="e2e-si-1")
    await c.connect()
    await c.listen_start()
    await c.stream(70)  # ≥2 轮 30s 重算，保证拿到带 todo 项的清单
    items = _latest_items(c)
    todos = [i for i, s in items.items() if s == "todo"]
    assert todos, "70s 推流后清单里没有任何 todo 项"

    victim_ign, victim_skip = todos[0], todos[-1]
    mark = len(c.records)  # 只考察发指令之后收到的帧
    await c.send_json({"type": "coaching.ignore", "id": victim_ign})
    await c.send_json({"type": "coaching.skip", "id": victim_skip})
    # 再推一轮让重算把用户动作收进清单
    await c.stream(40)
    assert not c.frames_of("error"), c.frames_of("error")

    final = _latest_items(c)
    assert final.get(victim_ign) == "ignored", f"忽略后状态为 {final.get(victim_ign)!r}"
    assert final.get(victim_skip) == "skipped", f"跳过后状态为 {final.get(victim_skip)!r}"
    # 用户终态不回跳：发指令之后的每帧里，两项都保持自己的终态
    for r in c.records[mark:]:
        if r["dir"] != "in" or r["kind"] != "coaching.update":
            continue
        for it in r["data"].get("items") or []:
            if it["id"] == victim_ign:
                assert it.get("status") == "ignored", f"ignored 回跳为 {it.get('status')}"
            if it["id"] == victim_skip:
                assert it.get("status") == "skipped", f"skipped 回跳为 {it.get('status')}"

    assert not check_frame_invariants(c.in_frames, c.name)
    await c.close()
    await asyncio.sleep(8)
    status, _ = await api.end_interview(sid)
    assert status in (200, 409), status


async def test_pause_by_disconnect_and_resume(api, new_sid, make_client):
    """断开 60s 宽限到期自动挂起；重连恢复 in_progress 且能继续出转写段落。"""
    sid = await new_sid("E2E暂停继续", "操作测试：断开自动挂起与重连恢复")
    c1 = make_client("pause1", sid, client_id="e2e-pz-1")
    await c1.connect()
    await c1.listen_start()
    await c1.stream(45)
    assert c1.frames_of("asr"), "挂起前应有转写段落"
    segs_before = {f["data"]["seg_id"] for f in c1.frames_of("asr")}
    await c1.close()

    # 宽限窗口内仍是 in_progress；到期自动转 suspended（多等检查余量）
    await asyncio.sleep(20)
    info = await api.get_interview(sid)
    assert info["status"] == "in_progress", f"宽限期内不应挂起：{info['status']}"
    await asyncio.sleep(GRACE_PERIOD_S + 15)
    info = await api.get_interview(sid)
    assert info["status"] == "suspended", f"宽限到期应自动挂起：{info['status']}"

    # 继续 = 重连（SUSPENDED→IN_PROGRESS），沿用同 client_id
    c2 = make_client("pause2", sid, client_id="e2e-pz-1")
    hello = await c2.connect()
    assert hello and hello.get("type") == "hello"
    info = await api.get_interview(sid)
    assert info["status"] == "in_progress", f"重连后应恢复进行中：{info['status']}"

    await c2.listen_start()
    await c2.stream(45)
    segs_after = {f["data"]["seg_id"] for f in c2.frames_of("asr")}
    assert segs_after - segs_before, "恢复后应有新增转写段落（非重放旧段）"
    assert not check_frame_invariants(c2.in_frames, c2.name)

    await c2.close()
    await asyncio.sleep(8)
    status, _ = await api.end_interview(sid)
    assert status in (200, 409), status


async def test_report_generation_and_export(api, new_sid, make_client):
    """结束后生成报告：结构完整（标题层级、无残留占位符、内容量）且可导出。"""
    sid = await new_sid("E2E报告", "操作测试：结束后的报告生成与导出")
    c = make_client("report", sid, client_id="e2e-rp-1")
    await c.connect()
    await c.listen_start()
    await c.stream(90)
    await c.listen_stop()
    await c.close()
    await asyncio.sleep(8)
    status, _ = await api.end_interview(sid)
    assert status in (200, 409), status

    # 落库完整性先行：转写为空的报告没有断言意义
    info = await api.get_interview(sid)
    assert info["transcript"], "会话转写为空"
    assert not check_interview_data(info, sid), check_interview_data(info, sid)

    rep = await api.get_report(sid)
    assert rep["status"] == "ready", rep["status"]
    md = rep["content_md"]

    headings = re.findall(r"^##+ .+$", md, re.MULTILINE)
    assert len(headings) >= 3, f"报告章节过少：{headings}"
    # 模板占位符须全部被填掉（{{skill:...}} 是技能标记，允许保留）
    orphans = [p for p in re.findall(r"\{\{.*?\}\}", md) if not p.startswith("{{skill:")]
    assert not orphans, f"报告残留未填占位符：{orphans[:5]}"
    # 章节标签后不能是空的：LLM 无内容可填时须明确写「未提及」，不许留空骨架。
    # 合法形态是标签后接同行内容或下一行缩进子条目；两者皆无 = 悬空标签。
    lines = md.splitlines()
    dangling = [
        ln for i, ln in enumerate(lines)
        if re.match(r"^\s*[-*]\s*.*[:：]\s*$", ln)
        and not (i + 1 < len(lines) and lines[i + 1][:1] in (" ", "\t"))
    ]
    assert not dangling, f"报告存在空章节标签（未填占位符）：{dangling[:5]}"
    # 报告是摘要改写，不要求逐字引用转写；有实质内容量即可
    assert len(md) > 600, f"报告内容量不足（{len(md)} 字符）"

    for fmt in ("md", "html", "word"):
        code, body = await api.export_report(sid, fmt)
        assert code == 200 and body, f"{fmt} 导出失败：{code}"
