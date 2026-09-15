"""issue #199：同一访谈两条 WS 并发握手 → 不留鬼连接。

场景：两个不同 client_id 的 WS handler 同时进入 _handshake。

修复前：双方都看到 _send_fn is None、都 send hello、都 bind。后到的 bind 把
_send_fn 静默覆盖，旧的连接 TCP 还开着但所有消息被 ownership 守卫丢弃，成为
「鬼连接」——前端任何按钮都没反应、刷新也救不回。

修复（两层防御）：
1. manager.get_handshake_lock(session_id) 把「conflict 检查 + hello + bind」原子
   化，后到的 handler 在锁外正确进入 conflict 分支。
2. runtime._bind_core 在覆盖不同身份 owner 时发送 connection.kicked + 关闭旧
   WS，即便锁失效也不会留下鬼连接。

本文件覆盖：
- 并发握手：一方拿到 hello、另一方收到 connection.conflict（锁路径）
- _bind_core 防御踢人：不同身份覆盖时旧 owner 收 kicked + evict 被调
- 并发接管（takeover）：旧 owner 不会被并发握手撞成 ghost
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.sessions.runtime import SessionRuntime
from app.transport.websocket.handler import WSHandler
from app.domain.session import SessionStatus

# 每个测试清 manager._handshake_locks——跨 event loop 复用 asyncio.Lock 会 RuntimeError。
pytestmark = pytest.mark.usefixtures("_reset_handshake_locks")


def _stub_runtime(rt: SessionRuntime) -> None:
    """挂最小桩，让 bind/takeover/_raw_send 走通而不触网/不落盘。"""
    rt._send_fn = None
    rt._save_state = AsyncMock()
    rt.pipeline.listen_start = AsyncMock()
    rt.pipeline.reset_provider = AsyncMock()
    rt.engine.on_bind = lambda: None
    rt.engine.on_unbind = lambda: None
    rt.engine.first_compute = AsyncMock()
    rt.engine.resend_current = AsyncMock()
    rt.engine.on_listen_resume = lambda: None


def _sent_types(send_mock) -> list[str]:
    return [c.args[0].get("type") for c in send_mock.call_args_list if c.args]


# _reset_handshake_locks fixture 在 tests/unit/conftest.py（跨 unit 套件共享）


# ── _bind_core 防御踢人（issue #199 防御层）────────────────────────────


async def test_bind_core_evicts_old_owner_on_different_client_id(make_state):
    """不同身份的 bind 撞上现役 owner → 发 connection.kicked + 调旧 evict_fn。

    即便 manager.get_handshake_lock 失效，_bind_core 自身仍能防止鬼连接。
    """
    rt = SessionRuntime(make_state())
    _stub_runtime(rt)
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)

    sendB, evictB = AsyncMock(), AsyncMock()
    await rt.bind(sendB, "clientB", evictB)

    # 新 owner 覆盖 _send_fn
    assert rt._send_fn is sendB
    assert rt._bound_client_id == "clientB"
    # 旧 owner A 收到 kicked 帧
    assert "connection.kicked" in _sent_types(sendA)
    # 旧 owner A 的 evict_fn 被调（关 WS）
    evictA.assert_awaited_once()
    # 新 owner B 不应收到 kicked
    assert "connection.kicked" not in _sent_types(sendB)


async def test_bind_core_no_evict_when_old_owner_gone(make_state):
    """_send_fn 已是 None（旧 owner 待决期间自行离开）→ bind 走正常路径，不踢人。"""
    rt = SessionRuntime(make_state())
    _stub_runtime(rt)
    # 模拟旧 owner 已 unbind：直接置 _send_fn = None
    sendB, evictB = AsyncMock(), AsyncMock()
    await rt.bind(sendB, "clientB", evictB)

    assert rt._send_fn is sendB
    assert rt._bound_client_id == "clientB"
    # 无人被踢，bind_core 不发消息
    assert sendB.call_args_list == []


async def test_bind_core_same_client_id_still_zombie_warn(make_state, caplog):
    """同身份覆盖仍存活的 send_fn 仍属 zombie 竞态（warning），不应踢人。"""
    import logging

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)

    sendA2, evictA2 = AsyncMock(), AsyncMock()
    with caplog.at_level(logging.WARNING, logger="app.services.sessions.runtime"):
        await rt.bind(sendA2, "clientA", evictA2)

    assert any("zombie" in r.message for r in caplog.records)
    # 同身份不踢人：evictA 没被新 bind 调
    evictA.assert_not_awaited()
    assert rt._send_fn is sendA2


# ── 并发握手：锁路径（issue #199 主修）─────────────────────────────────


def _make_handler(sid: str, client_id: str) -> WSHandler:
    """构造一个 _handshake 可跑通到 conflict 检查的 handler（manager/registry 全桩）。

    本 helper 不构造 rt——调用方各自决定 rt 类型并 stub。

    rt stub 注意：
    - 调用方若用真实 SessionRuntime（见 _stub_runtime），其 _fsm 由 RuntimeStateMachine
      管理，默认 LIVE_PAUSED → is_terminated=False，无需额外 stub。
    - 调用方若用 MagicMock rt（见 test_ws_error_codes.py /
      test_ws_hello_protocol_version.py），须置 rt._fsm.is_terminated = False——
      MagicMock 默认 truthy，会被 _handshake 锁内 is_terminated 守卫误判 terminated
      直接 _fail。
    """
    ws = MagicMock()
    ws.scope = {"subprotocols": []}
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock(
        return_value=json.dumps({"type": "hello", "client_id": client_id})
    )
    h = WSHandler(ws, sid)
    h._user = SimpleNamespace(user_id="u1")
    h.client_id = client_id
    return h


@pytest.mark.asyncio
async def test_concurrent_handshake_different_client_id_one_hello_one_conflict(
    monkeypatch, make_state
):
    """两个不同 client_id 并发 _handshake 同一 session → 一个拿到 hello、另一个拿到 conflict。

    修复前：双方都拿到 hello，第二条变成鬼连接。
    修复后：manager.get_handshake_lock 串行化，后到的在锁内看到 _send_fn 已设、
    client_id 不同 → 走 conflict 分支。
    """
    import app.transport.websocket.handler as h_mod

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "race-sid"
    fake_state.status = SessionStatus.IN_PROGRESS
    fake_state.locale = "en-US"
    fake_state.session.consumed_seq = 0
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "on_reconnect", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "touch", lambda *a, **k: None)

    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda *a, **k: False)
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)

    hA = _make_handler("race-sid", "client-A")
    hB = _make_handler("race-sid", "client-B")

    # 启动两个 _handshake，让锁去串行化
    a_result, b_result = await asyncio.gather(hA._handshake(), hB._handshake())

    # 两个都返回 True（一个拿 hello、另一个拿 conflict，都进入 _loop 等后续事件）
    assert a_result is True and b_result is True

    # 各自 ws.send_json 的 type 集合
    types_a = [c.args[0].get("type") for c in hA.ws.send_json.call_args_list if c.args]
    types_b = [c.args[0].get("type") for c in hB.ws.send_json.call_args_list if c.args]

    # 两边合计恰好一个 hello + 一个 conflict（无论谁先抢到锁都满足）
    assert types_a.count("hello") + types_b.count("hello") == 1
    assert types_a.count("connection.conflict") + types_b.count("connection.conflict") == 1


@pytest.mark.asyncio
async def test_concurrent_handshake_same_client_id_both_hello(monkeypatch, make_state):
    """同身份（同标签刷新/断网重连）并发握手都拿 hello —— 无 conflict（无缝复用）。"""
    import app.transport.websocket.handler as h_mod

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "race-sid"
    fake_state.status = SessionStatus.IN_PROGRESS
    fake_state.locale = "en-US"
    fake_state.session.consumed_seq = 0
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "on_reconnect", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "touch", lambda *a, **k: None)

    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda *a, **k: False)
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)

    hA = _make_handler("race-sid", "client-X")
    hB = _make_handler("race-sid", "client-X")

    a_result, b_result = await asyncio.gather(hA._handshake(), hB._handshake())
    assert a_result is True and b_result is True

    types_a = [c.args[0].get("type") for c in hA.ws.send_json.call_args_list if c.args]
    types_b = [c.args[0].get("type") for c in hB.ws.send_json.call_args_list if c.args]
    assert types_a.count("hello") + types_b.count("hello") == 2
    assert "connection.conflict" not in types_a
    assert "connection.conflict" not in types_b


@pytest.mark.asyncio
async def test_takeover_under_lock_kicks_and_sends_hello(monkeypatch, make_state):
    """_on_takeover 在 lock 包裹下调 takeover，旧 owner 应被踢、新 owner 收 hello。"""
    import app.transport.websocket.handler as h_mod

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)

    # 已有 owner A（不同 client_id），待决连接 B 来接管
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "take-sid"
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=fake_state))

    hB = _make_handler("take-sid", "clientB")
    hB.runtime = rt

    await hB._on_takeover()

    # 新 owner 是 B
    # bound method 比较：用 == 而非 is（同实例同方法的 ==/is 都 True，
    # 但被绑到不同对象上的同源代码方法在这里意外 is False——直接 == 更稳）。
    assert rt._send_fn == hB._send
    assert rt._bound_client_id == "clientB"
    # 旧 owner A 收到 kicked + evict 被调
    assert "connection.kicked" in _sent_types(sendA)
    evictA.assert_awaited_once()
    # B 收到 hello
    sent_b = [c.args[0].get("type") for c in hB.ws.send_json.call_args_list if c.args]
    assert "hello" in sent_b


# ── 并发 takeover + handshake（issue #199 最直接的场景）────────────────


@pytest.mark.asyncio
async def test_concurrent_takeover_and_handshake_same_runtime(
    monkeypatch, make_state
):
    """旧 owner A 已 parked（_send_fn=None）→ B（pending 接管）和 C（新握手）并发进入：
    B 走 _on_takeover 走 reactivation 分支 + 接管；C 走 _handshake 走 conflict / bind。
    验证两者拿同一条 runtime、锁内串行化、不出现两个 hello / 鬼连接。

    这是 issue #199 的最直接修复场景——真并发同时进 _on_takeover + _handshake。
    """
    import app.transport.websocket.handler as h_mod

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)
    # 模拟旧 owner A 已走（parked）：_send_fn = None
    rt._send_fn = None
    rt._bound_client_id = None
    rt._evict_fn = None

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "race-tk-sid"
    fake_state.session.consumed_seq = 0
    fake_state.status = SessionStatus.IN_PROGRESS
    fake_state.locale = "en-US"
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "on_reconnect", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "touch", lambda *a, **k: None)

    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda *a, **k: False)
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)

    # B：pending 连接，发 connection.takeover（其 _send_fn is None → 走 reactivation）
    hB = _make_handler("race-tk-sid", "client-B")
    hB.runtime = rt
    # C：全新连接，发 hello
    hC = _make_handler("race-tk-sid", "client-C")

    # 真并发：B 接管 + C 握手
    b_result, c_result = await asyncio.gather(hB._on_takeover(), hC._handshake())

    # _on_takeover 返回 None；_handshake 返回 True（拿到 hello 或被拒）。
    # 真重要的不是返回值，而是下面 rt 的 owner 状态。
    assert c_result is True

    # 锁内串行化的最终结果：rt._send_fn 必定是 B 或 C 之一（不可能两者都绑成 ghost）。
    # 锁外再并发读一次：之前的实现会让两边都 hello、_send_fn 是后到者（鬼连接）。
    assert rt._send_fn in (hB._send, hC._send)

    # 必有一方是最终 owner：loser 一定收到 conflict（新加的 _on_takeover 冲突守卫 +
    # _handshake 冲突守卫都发 conflict）。绝不允许：loser 只收到 hello 但仍在线——
    # 这就是 issue #199 的鬼连接。
    if rt._send_fn == hB._send:
        winner, loser = hB, hC
    else:
        winner, loser = hC, hB
    loser_sent = [c.args[0].get("type") for c in loser.ws.send_json.call_args_list if c.args]
    winner_sent = [c.args[0].get("type") for c in winner.ws.send_json.call_args_list if c.args]
    assert "connection.conflict" in loser_sent, (
        f"锁正常工作时 loser 必须收到 conflict；loser_sent={loser_sent}"
    )
    # kicked 不应出现——只有锁失效、退到 _bind_core defense-in-depth 兜底时才会走 kicked。
    # 若本断言失败，说明锁路径退化，须调查而非放宽断言。
    assert "connection.kicked" not in loser_sent, (
        f"锁路径退化（kicked 出现意味着锁失效）；loser_sent={loser_sent}"
    )
    # winner 一定收到 hello（接管路径走 takeover → hello；握手路径走 hello → bind）
    assert "hello" in winner_sent, f"winner 必收到 hello；winner_sent={winner_sent}"


# ── 旧 owner _cleanup 在 await old_evict() 期间并发跑的覆盖 ──────────────


async def test_bind_core_state_flip_before_old_evict_await(make_state):
    """状态翻转必须在 await old_evict() 之前——否则旧 owner _cleanup 撞过
    ownership 守卫把 _send_fn 置 None、把 runtime 误拆到 _parked，TTL 到期
    后被 end() 误踢。

    用 side_effect 拦 evictA：调用时记录 _send_fn 的当前值。若 _send_fn 已
    是 sendB（B 的 send），说明状态翻转已完成。
    """
    rt = SessionRuntime(make_state())
    _stub_runtime(rt)

    sendA = AsyncMock()
    observed = []

    async def evictA_checking_ownership():
        # A 的 _cleanup 此刻进入：必须看到 _send_fn 已变（否则就走 unbind + park）
        observed.append(rt._send_fn)

    await rt.bind(sendA, "clientA", evictA_checking_ownership)

    sendB = AsyncMock()
    evictB = AsyncMock()
    await rt.bind(sendB, "clientB", evictB)

    # 关键断言：旧 owner evict 跑的时候，_send_fn 已经是 sendB 了。
    # 若此断言失败，runtime 在 await old_evict() 期间还有窗口被旧 _cleanup unbind。
    assert len(observed) == 1 and observed[0] is sendB, (
        f"状态翻转必须在 await old_evict() 之前——否则旧 _cleanup 会 unbind "
        f"把 runtime 误拆到 _parked；observed={observed}"
    )
    # 副断言：覆盖 runtime.unbind 的 ownership 守卫——_bind_core 状态翻转后
    # 旧 owner 的迟到 unbind 还能被 unbind 守卫兜住。
    assert await rt.unbind(sendA) is False, "旧 owner 迟到 unbind 必须因 ownership 不符 no-op"
    # 新 owner 仍是 B（确认 unbind 没踩坏）
    assert rt._send_fn is sendB


# ── 两个并发 takeover（方案 A 锁内冲突守卫）────────────────────────


@pytest.mark.asyncio
async def test_two_concurrent_takeovers_second_yields_conflict(
    monkeypatch, make_state
):
    """两个 pending 连接 B、C 同时进 _on_takeover（旧 owner A 已 parked）→
    先入 reactivation 拿 rt 者正常 takeover；后入锁时 _send_fn 已被覆盖且
    client_id 不同 → 锁内冲突守卫命中 → 发 connection.conflict，不踢人。

    这与 _handshake 路径行为对称：「不是自己的 → conflict 不踢」。

    client_id 必须不同（client-B vs client-C）——若相同 _on_takeover 走正常
    路径（_send_fn 已变 + client_id 一致 = 自己就是 owner）不发 conflict。

    `_fake_get` 里的 `await asyncio.sleep(0)` 是必需的：mock 环境下若 await
    同步 resolve，B 会同步跑完 reactivation 后 C 才启动，C 的 entry 检查
    `rt._send_fn is None` 看到的是 B 已设的 sendB，reactivated 误设 False，
    冲突守卫不触发，整个测试退化为 second-kicks-first 旧行为。真生产环境
    网络/DB await 真挂起，并发自然生效；测试里需这层强制让出。
    """
    import app.transport.websocket.handler as h_mod

    rt = SessionRuntime(make_state())
    _stub_runtime(rt)
    # 旧 owner A 已走：parked
    rt._send_fn = None
    rt._bound_client_id = None
    rt._evict_fn = None

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "two-tk-sid"

    async def _fake_get(sid):
        # sleep(0) 强制让出——见本测试 docstring
        await asyncio.sleep(0)
        return fake_state
    monkeypatch.setattr(h_mod.manager, "get", _fake_get)
    # get_or_create 返回原 rt——避免 fake_state 的 MagicMock template_id 触发 engine 真实构造
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)

    hB = _make_handler("two-tk-sid", "client-B")
    hB.runtime = rt
    hC = _make_handler("two-tk-sid", "client-C")
    hC.runtime = rt

    # 真并发：两个 takeover
    await asyncio.gather(hB._on_takeover(), hC._on_takeover())

    # 最终 owner 必是 B 或 C 之一（先抢锁者拿到 rt + takeover；后入锁者被冲突守卫拒）
    assert rt._send_fn in (hB._send, hC._send)
    winner = hB if rt._send_fn == hB._send else hC
    loser = hC if winner is hB else hB

    # winner 收到 hello
    sent_w = [c.args[0].get("type") for c in winner.ws.send_json.call_args_list if c.args]
    assert "hello" in sent_w

    # loser 收到 conflict（被锁内守卫拒，不踢人）
    sent_l = [c.args[0].get("type") for c in loser.ws.send_json.call_args_list if c.args]
    assert "connection.conflict" in sent_l, (
        f"loser 应收到 conflict（方案 A 锁内守卫）；sent_l={sent_l}"
    )
    # loser 不应收到 kicked（与原 second-kicks-first 设计区分）
    assert "connection.kicked" not in sent_l, (
        f"方案 A 下 loser 不应被踢；sent_l={sent_l}"
    )


# ── _handshake is_terminated 守卫（与 _on_takeover 守卫对称）───────────────


@pytest.mark.asyncio
async def test_handshake_terminated_session_rejected(monkeypatch, make_state):
    """runtime 已被并发路径置 TERMINATED 但还没从 registry 摘除 → 新连接进来
    必须被拒（session_ended），不能进入 conflict 分支后等死。
    """
    import app.transport.websocket.handler as h_mod

    rt = MagicMock()
    # MagicMock 默认 truthy，但这里要表达 terminated=True——显式赋 True 让意图清晰
    rt._fsm.is_terminated = True
    rt._send_fn = None
    rt._bound_client_id = None

    fake_state = MagicMock()
    fake_state.session.user_id = "u1"
    fake_state.session.id = "term-sid"
    fake_state.status = SessionStatus.IN_PROGRESS  # start/on_reconnect 不会拒
    fake_state.locale = "en-US"
    fake_state.session.consumed_seq = 0
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "on_reconnect", AsyncMock(return_value=fake_state))
    monkeypatch.setattr(h_mod.manager, "touch", lambda *a, **k: None)
    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda *a, **k: False)
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: rt)

    hA = _make_handler("term-sid", "client-A")

    result = await hA._handshake()
    # is_terminated 命中 → _fail + return False（不进 _loop）
    assert result is False

    # 验证：close_code=4406 + code=session_ended（通过 ws.close 调参数）
    close_calls = hA.ws.close.call_args_list
    assert any(c.kwargs.get("code") == 4406 for c in close_calls), (
        f"terminated 会话必须用 4406 关 WS；close_calls={close_calls}"
    )
    # 验证：没发出 hello（应直接 fail）
    sent_types = [c.args[0].get("type") for c in hA.ws.send_json.call_args_list if c.args]
    assert "hello" not in sent_types, (
        f"terminated 会话不应收到 hello；sent={sent_types}"
    )