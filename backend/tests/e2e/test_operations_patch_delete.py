"""访谈过程的 REST 写路径：PATCH（编辑 base_info/goal）+ DELETE（删除访谈）。

黑盒盲区里最值得补的两块：
- 源码里"PATCH 寄存期静默丢失"有专门防御，但 e2e 一道都没守门——本文件直接
  戳穿：进行中 PATCH 必须 409，绝不能静默成 200 假装成功。
- "删后 grace 到期复活僵尸行"也有防御，e2e 同样没有——验证 suspended 删完
  等存活窗口到期 get 回 404，不会凭空再冒一行回来。

PATCH 只在 created / suspended 态合法；DELETE 在 created / suspended / ended
合法，进行中（setting_up/in_progress）一律 409。
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.e2e

GRACE_PERIOD_S = 60   # 与 test_operations 对齐：复用既有挂起窗口语义


# ---- PATCH ----


async def test_patch_on_created_succeeds(api, new_sid):
    """创建后（created，未连 WS）PATCH base_info / goal：200 + GET 回显变更。"""
    sid = await new_sid("E2E编辑-创建态", "PATCH：未开始可编辑")
    code, _ = await api.patch_interview(sid, {
        "base_info": {"title": "改名-创建态", "note": "patched"},
        "goal": "patched goal",
    })
    assert code == 200
    info = await api.get_interview(sid)
    assert info["base_info"].get("title") == "改名-创建态"
    assert info["base_info"].get("note") == "patched"
    assert info["goal"] == "patched goal"


async def test_patch_on_in_progress_returns_409(api, new_sid, make_client):
    """WS 推流中 PATCH 必须 409——这是「寄存期 PATCH 静默丢失」的镜像：
    用户在访谈进行中改资料被静默接收不会报错，那是数据漂移；正确语义是拒绝。

    这是源码专门防御的分支，黑盒必须守住，否则未来重构一旦改坏会毫无征兆。
    """
    sid = await new_sid("E2E编辑-进行中", "PATCH：进行中必须被拒")
    c = make_client("patchip", sid, client_id="e2e-pp-1")
    await c.connect()
    await c.listen_start()
    # 推短流，确到 in_progress；不必出段——只验 PATCH 守门
    await c.stream(10)

    code, body = await api.patch_interview(sid, {"goal": "should not stick"})
    assert code == 409, f"进行中 PATCH 应返回 409，实际 {code}：{body}"
    info = await api.get_interview(sid)
    assert info["goal"] != "should not stick", "进行中 PATCH 不应改写 goal"

    await c.close()


async def test_patch_on_suspended_succeeds(api, new_sid, make_client):
    """断开过 grace 后到 suspended 态，PATCH 应允许并能看到。"""
    sid = await new_sid("E2E编辑-挂起态", "PATCH：挂起态可编辑")
    c = make_client("patchsp", sid, client_id="e2e-ps-1")
    await c.connect()
    await c.listen_start()
    await c.stream(15)
    await c.close()
    # 等进 suspended（宽限默认 60s + 余量）
    await asyncio.sleep(GRACE_PERIOD_S + 15)
    info = await api.get_interview(sid)
    assert info["status"] == "suspended", f"未到 suspended：{info['status']}"

    code, _ = await api.patch_interview(sid, {"goal": "edited-while-suspended"})
    assert code == 200
    info = await api.get_interview(sid)
    assert info["goal"] == "edited-while-suspended"


async def test_patch_on_suspended_survives_reconnect_by_same_client(
        api, new_sid, make_client, restore_runtime_windows):
    """PATCH 真正要守的门不是"挂起态改了能读到"，而是「寄存期 PATCH 后同
    client_id 重连接管 runtime，落库不能被旧 snapshot 覆盖回旧 goal」。

    复用路径条件：重连时 get_or_create 必须看到 _parked 内仍有该 session——
    即 grace 已到 suspended（脱离 _active 进入 _parked）、liveness 未到期。
    默认 grace=60s == liveness=60s，几乎同时到期，所以默认下运行时已被
    liveness 销毁，重连命中的是「读 DB 现值新建 runtime」分支，根本走不到
    registry.get_or_create 里那段 _refresh_session_fields 旧-新刷新——这条
    用例也就在错的原因下通过。

    必须把 grace 缩到 < liveness，造一个"suspended 已成立且 runtime 仍寄存"
    的稳态。这里 grace=15s / liveness=60s：用例 ≈15+5 + 60 余量走完。
    """
    async with restore_runtime_windows(grace_s="15", liveness_s="60"):
        sid = await new_sid("E2E编辑-重连守门", "PATCH：挂起寄存后重连不回滚")
        c1 = make_client("patchrc", sid, client_id="e2e-prc-1")
        await c1.connect()
        await c1.listen_start()
        await c1.stream(15)
        await c1.close()

        # 等 grace 到 suspended；liveness 60s 仍有大量余量让重连命中复用路径
        await asyncio.sleep(15 + 5)
        info = await api.get_interview(sid)
        assert info["status"] == "suspended", f"suspended 未到：{info['status']}"

        # PATCH 改 goal + base_info（守住两条编辑路径都生效）。PATCH 自身直接落盘。
        code, _ = await api.patch_interview(sid, {
            "base_info": {"title": "重连后仍存"},
            "goal": "edit-while-suspended",
        })
        assert code == 200

        # 紧接一段让 PATCH 落盘稳定 + 仍在 liveness 窗口内的重连：必须命中
        # registry.get_or_create → _refresh_session_fields 这条复用路径，
        # 把 DB 现值（PATCH 后的 goal/base_info）灌回 runtime 内部 snapshot。
        c2 = make_client("patchrc_resume", sid, client_id="e2e-prc-1")
        hello = await c2.connect()
        assert hello and hello.get("type") == "hello"
        await c2.listen_start()
        await c2.stream(8)
        await c2.listen_stop()
        # 让 PATCH 后又一段推流把新 runtime 状态彻底落盘
        await asyncio.sleep(8)

        info = await api.get_interview(sid)
        assert info["goal"] == "edit-while-suspended", (
            f"重连后 goal 被旧 snapshot 覆盖：{info['goal']!r}"
        )
        assert info["base_info"].get("title") == "重连后仍存", (
            f"重连后 base_info.title 被覆盖：{info['base_info'].get('title')!r}"
        )
        await c2.close()


# ---- DELETE ----


async def test_delete_on_created_succeeds(api, new_sid):
    """未开始的访谈可删：DELETE 200 即视为通过；GET 404 由后续 zombie 用例覆盖。"""
    sid = await new_sid("E2E删除-创建态", "DELETE：未开始可删")
    code, _ = await api.delete_interview(sid)
    assert code == 200


async def test_delete_on_in_progress_returns_409(api, new_sid, make_client):
    """进行中拒绝删除（409）；删被拒后会话依然健康，关流后可继续 end。"""
    sid = await new_sid("E2E删除-进行中", "DELETE：进行中必须被拒")
    c = make_client("delip", sid, client_id="e2e-dp-1")
    await c.connect()
    await c.listen_start()
    await c.stream(10)

    code, body = await api.delete_interview(sid)
    assert code == 409, f"进行中 DELETE 应返回 409，实际 {code}：{body}"
    info = await api.get_interview(sid)
    assert info["status"] == "in_progress", "拒删后状态不应变"

    await c.close()


async def test_delete_on_suspended_does_not_resurrect_zombie(api, new_sid, make_client,
                                                            restore_runtime_windows):
    """suspended 删除：200 后存活窗口到期不再 '复活' 出一行（注册 runtime 先 drop
    再 delete 的顺序修复）。

    默认 grace_period_s 与 liveness_window_s 同为 60s，几乎同时触发，运行时
    早在 DELETE 调用前就随 liveness 到期销毁；没有"runtime 仍寄存"的窗口，
    即便源码顺序写错（不 drop 就 delete）也照样通过。同时即便把 liveness 调到
    大值，又得等到过期才验得着——CI 不友好。

    选了 grace=15s / liveness=60s：
    - grace 短：用例快速进 suspended（约 15+5 = 20s 即可）
    - liveness 略长：删完到 liveness 到期 ≈ 60+5 = 65s 后再验 404，可 CI 跑
    - DELETE 仍能让 manager.delete 先 registry.drop 然后再做 end()/save_state，
      不再依赖此后任何路径再"重建行"
    - 若源码顺序写错（先 delete 再 drop）：liveness 到期触发 runtime.end() →
      save_state 在行缺失时重建——GET 应重现这行

    防御分支语义：manager.delete 应先 registry.drop（取消存活定时器）
    再 interview_repo.delete（行 SQL 删除）；颠倒就先删行后定时器到点重建行——
    复活成僵尸行，GET 在 liveness 到期后会重现这行。修后版则始终 404。
    """
    async with restore_runtime_windows(grace_s="15", liveness_s="60"):
        sid = await new_sid("E2E删除-挂起态", "DELETE：suspended 不能复活成僵尸行")
        c = make_client("delsp", sid, client_id="e2e-ds-1")
        await c.connect()
        await c.listen_start()
        await c.stream(15)
        await c.close()

        # 仅等 grace 到 suspended；liveness 60s，运行时仍在 registry
        await asyncio.sleep(15 + 5)
        info = await api.get_interview(sid)
        assert info["status"] == "suspended"

        # 用 DELETE 默认 90s httpx 超时覆盖 runtime.end() 终算 LLM（上限 60s）+ save
        code, _ = await api.delete_interview(sid)
        assert code == 200

        # 第一道：当场 GET 应 404（删完了）
        async with await api._client() as c2:
            r = await c2.get(f"/api/v1/interviews/{sid}", headers=await api._auth_headers())
            assert r.status_code == 404, (
                f"删除后立即 GET 非 404：当前 status={r.status_code}"
            )

        # 第二道：等到 liveness（60s）真正到期 + 余量——这才是这条用例的"靶"：
        # 若源码顺序写错（不 drop），到期会触发 runtime.end() → save_state 在行
        # 缺失时重建行——GET 应重现这行（200）。修后版则始终 404。
        await asyncio.sleep(60 + 5)
        async with await api._client() as c3:
            r2 = await c3.get(f"/api/v1/interviews/{sid}", headers=await api._auth_headers())
            assert r2.status_code == 404, (
                f"liveness 到期后行被重建（复活）：GET 返回 {r2.status_code}；"
                "manager.delete 应先 registry.drop 再 interview_repo.delete"
            )


async def test_delete_on_ended_succeeds(api, new_sid, make_client):
    """正常结束后删除：200 + 后续 GET 404（不被终算重算 LLM 复活）。"""
    sid = await new_sid("E2E删除-已结束", "DELETE：ended 态可清")
    c = make_client("deled", sid, client_id="e2e-de-1")
    await c.connect()
    await c.listen_start()
    await c.stream(40)
    await c.close()
    await asyncio.sleep(8)
    code, _ = await api.end_interview(sid)
    assert code in (200, 409), code

    code, _ = await api.delete_interview(sid)
    assert code == 200, code

    async with await api._client() as c2:
        r = await c2.get(f"/api/v1/interviews/{sid}", headers=await api._auth_headers())
        assert r.status_code == 404
