"""连接竞争 / 接管（takeover）协议单元测试。

同一访谈只允许一个活跃 owner。第二个不同身份的连接进来 → 走 WS 消息协议
（connection.conflict / connection.takeover / connection.kicked）协商接管，
而非两条连接并发喂同一个解码器（那会让簇边界错乱、两端都不出字）。

身份按 client_id 判定（前端 sessionStorage）：同身份=同端的刷新/断网重连（静默复用），
不同身份=另一端接管。这里覆盖 runtime.takeover 的踢人/绑定/ownership 语义，以及
WSHandler 的入站 ownership 守卫与 _on_takeover 编排。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.runtime import SessionRuntime
from app.transport.websocket.handler import WSHandler


def _binds(rt: SessionRuntime) -> None:
    """挂最小桩，让 bind/_bind_core/unbind 走通而不触网/不落盘。"""
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
    """从 AsyncMock send_fn 的调用里提取所有发出的消息 type。"""
    return [c.args[0].get("type") for c in send_mock.call_args_list if c.args]


# ── runtime.takeover ──────────────────────────────────────────────────

async def test_takeover_kicks_old_owner_and_binds_new(make_state):
    """有旧 owner 时：发 connection.kicked 给旧 owner + 调其 evict_fn 关 WS + 绑新 owner。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)
    assert rt._send_fn is sendA and rt._bound_client_id == "clientA"

    sendB, evictB = AsyncMock(), AsyncMock()
    await rt.takeover(sendB, "clientB", evictB)

    # 新 owner = B
    assert rt._send_fn is sendB
    assert rt._bound_client_id == "clientB"
    assert rt._evict_fn is evictB
    # 旧 owner A 收到 kicked，其 evict_fn 被调（关 A 的 WS）
    assert "connection.kicked" in _sent_types(sendA)
    evictA.assert_awaited_once()
    # 新 owner B 不应收到 kicked
    assert "connection.kicked" not in _sent_types(sendB)


async def test_takeover_skips_kick_when_no_owner(make_state):
    """旧 owner 已自行离开（_send_fn 空，如待决期间断连）→ 不踢人、直接绑新。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    sendB, evictB = AsyncMock(), AsyncMock()
    await rt.takeover(sendB, "clientB", evictB)
    assert rt._send_fn is sendB
    assert rt._bound_client_id == "clientB"
    assert sendB.call_args_list == []   # 无人被踢，bind_core 也不发消息


async def test_takeover_same_client_id_does_not_self_kick(make_state):
    """同身份（同端重连）takeover 不应踢「自己」——should_kick 按 client_id 判定。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)
    # 同 client_id 的 takeover：无意义但不应误发 kicked / 误调 evict
    sendA2, evictA2 = AsyncMock(), AsyncMock()
    await rt.takeover(sendA2, "clientA", evictA2)
    assert "connection.kicked" not in _sent_types(sendA)
    evictA.assert_not_awaited()
    assert rt._send_fn is sendA2


async def test_old_owner_late_unbind_is_noop_after_takeover(make_state):
    """接管后旧 owner 迟到的 unbind(自己的 send) 必须 no-op——不能抹掉新 owner。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    sendA, evictA = AsyncMock(), AsyncMock()
    await rt.bind(sendA, "clientA", evictA)
    sendB, evictB = AsyncMock(), AsyncMock()
    await rt.takeover(sendB, "clientB", evictB)

    result = await rt.unbind(sendA)   # 旧 owner 的 cleanup
    assert result is False
    assert rt._send_fn is sendB
    assert rt._bound_client_id == "clientB"


async def test_bind_same_client_id_over_living_is_zombie_warn(make_state, caplog):
    """同身份覆盖仍存活的 send_fn 属 zombie 竞态（异常），记 warning 而非 takeover info。"""
    import logging
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock(), "clientA", AsyncMock())
    with caplog.at_level(logging.WARNING, logger="app.services.sessions.runtime"):
        await rt.bind(AsyncMock(), "clientA", AsyncMock())
    assert any("zombie" in r.message for r in caplog.records)


# ── WSHandler 入站 ownership 守卫 ─────────────────────────────────────

async def test_dispatch_ignores_inbound_from_non_owner():
    """非当前 owner（pending / 已被接管）的 listen / 音频一律忽略，不污染他人会话。"""
    fake_ws = AsyncMock()
    h = WSHandler(fake_ws, "s1")
    rt = MagicMock()
    rt._send_fn = AsyncMock()   # 别的 owner（不是 h._send）
    h.runtime = rt

    await h._dispatch({"type": "listen", "state": "start"})
    rt.listen_start.assert_not_called()
    await h._on_audio(b"\x00\x00\x00\x01audio")
    rt.submit_audio.assert_not_called()


async def test_dispatch_routes_takeover_before_ownership_guard():
    """connection.takeover 由 pending（未 bind）连接发出，必须在 ownership 守卫之前放行。"""
    fake_ws = AsyncMock()
    h = WSHandler(fake_ws, "s1")
    rt = MagicMock()
    rt._send_fn = "someone-else"   # h 不是 owner
    h.runtime = rt
    called = []
    async def fake_takeover(): called.append(1)
    h._on_takeover = fake_takeover

    await h._dispatch({"type": "connection.takeover"})
    assert called == [1]


# ── WSHandler._on_takeover 编排 ───────────────────────────────────────

async def test_on_takeover_calls_runtime_takeover_and_sends_hello():
    """旧 owner 仍在：直接 rt.takeover(踢+绑)，再回 hello（resume_from_seq）让前端开麦。"""
    fake_ws = AsyncMock()
    h = WSHandler(fake_ws, "s1")
    h.client_id = "clientB"
    rt = MagicMock()
    rt._fsm.is_terminated = False
    rt._send_fn = AsyncMock()        # 有旧 owner → 不走 reactivation 分支
    rt.state = MagicMock()
    rt.seq.resume_from_seq = 42
    rt.takeover = AsyncMock()

    h.runtime = rt
    await h._on_takeover()

    rt.takeover.assert_awaited_once()
    args = rt.takeover.call_args.args
    assert args[1] == "clientB"
    assert args[2] == h._self_evict
    sent = [c.args[0] for c in fake_ws.send_json.call_args_list]
    assert any(
        isinstance(m, dict) and m.get("type") == "hello" and m.get("resume_from_seq") == 42
        for m in sent
    )


async def test_on_takeover_reactivates_parked_runtime_when_owner_gone(monkeypatch):
    """旧 owner 待决期间已离开（_send_fn 空）→ 重新 get_or_create 取回（取消 park TTL）再接管。"""
    import app.transport.websocket.handler as h_mod

    fake_ws = AsyncMock()
    h = WSHandler(fake_ws, "s1")
    h.client_id = "clientB"
    rt = MagicMock()
    rt._fsm.is_terminated = False
    rt._send_fn = None              # 旧 owner 已走
    rt.state = MagicMock()
    h.runtime = rt

    reactivated = MagicMock()
    reactivated._fsm.is_terminated = False
    reactivated.state = MagicMock()
    reactivated.seq.resume_from_seq = 7
    reactivated.takeover = AsyncMock()
    monkeypatch.setattr(h_mod.registry, "get_or_create", lambda *a, **k: reactivated)

    await h._on_takeover()
    reactivated.takeover.assert_awaited_once()
    assert h.runtime is reactivated


async def test_on_takeover_refuses_if_terminated():
    """会话已结束（runtime terminated）时接管无意义 → 回 session_ended 并关连接。"""
    fake_ws = AsyncMock()
    h = WSHandler(fake_ws, "s1")
    h.client_id = "clientB"
    rt = MagicMock()
    rt._fsm.is_terminated = True
    h.runtime = rt
    fails = []
    async def fake_fail(code, message, close_code=4000): fails.append(code)
    h._fail = fake_fail

    await h._on_takeover()
    assert fails == ["session_ended"]
    rt.takeover.assert_not_called()
