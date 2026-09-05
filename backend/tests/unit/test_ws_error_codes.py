from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.i18n.errors import SessionIllegalTransitionError
# Legacy alias still importable & is the SAME class.
from app.core.exceptions import IllegalTransitionError  # noqa: F401
from app.domain.session import SessionStatus
from app.transport.websocket.handler import WSHandler


async def test_internal_error_does_not_leak_detail(monkeypatch):
    """内部异常回前端的 message 不含 str(e)。"""
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=RuntimeError("DB password=hunter2"))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    user = MagicMock()
    user.user_id = "u1"
    monkeypatch.setattr(h_mod, "extract_auth", AsyncMock(return_value=user))
    h = WSHandler(ws, "s1")
    # _handshake 抛内部异常 → run 的兜底 except
    await h.run()
    sent = ws.send_json.call_args.args[0]
    assert sent["code"] == "internal"
    assert "hunter2" not in sent["message"]
    assert sent["message"]  # 有友好文案


async def test_bad_token_rejected_before_accept():
    """坏 token：accept 之前直接拒绝握手，不进消息循环占资源。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.not-a-jwt"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    h = WSHandler(ws, "s1")
    await h.run()
    ws.accept.assert_not_awaited()
    ws.receive_text.assert_not_awaited()
    ws.close.assert_awaited_once()


async def test_missing_token_rejected_before_accept():
    """无 token 子协议：同样在 accept 之前被拒。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": []}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    h = WSHandler(ws, "s1")
    await h.run()
    ws.accept.assert_not_awaited()
    ws.receive_text.assert_not_awaited()
    ws.close.assert_awaited_once()


async def test_handshake_on_ended_session_returns_4406(monkeypatch):
    """连接已结束的访谈：session_ended + 4406，而非漏成 internal + 4000。"""
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps(
        {"type": "hello", "client_id": "c1"}))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    state = MagicMock()
    state.session.user_id = "u1"
    state.status = SessionStatus.ENDED
    state.locale = None

    async def _get(sid):
        return state

    async def _start(sid):
        raise SessionIllegalTransitionError(from_state="ended", to_state="in_progress")

    monkeypatch.setattr(h_mod.manager, "get", _get)
    monkeypatch.setattr(h_mod.manager, "start", _start)

    h = WSHandler(ws, "s1")
    h._user = MagicMock(user_id="u1")  # run() 已在 accept 前完成鉴权
    assert not await h._handshake()
    sent = ws.send_json.call_args.args[0]
    assert sent["code"] == "session_ended"
    assert ws.close.call_args.kwargs["code"] == 4406


async def test_fail_payload_carries_i18n_params():
    """#PR1: _fail 把传入的 **params 一并写入 payload 的 i18n_params 字段，
    前端可用 i18n_params + i18n_key 完整渲染。"""
    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps(
        {"type": "hello", "client_id": "c1", "locale": "en-US"}))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    # 触发 _fail 的 concurrent_limit 路径需要 manager.get 返回有效 state，
    # 这里直接走 frame_too_large 触发 _fail(limit=...)，更简单：
    from app.transport.websocket.handler import _fail
    await _fail(ws, code="frame_too_large", close_code=4410, max_kb=64)
    sent = ws.send_json.call_args.args[0]
    assert sent["i18n_key"] == "ws.frame.too_large"
    assert sent["i18n_params"] == {"max_kb": 64}


async def test_handshake_sends_connection_conflict_with_i18n_params(monkeypatch):
    """PR1: _handshake 在已有不同身份的 owner 时，向**新连接**发
    connection.conflict 帧（含 i18n_params={}），新端据此决定是否发
    connection.takeover。

    锁三件事：
      1. 帧字段契约：type=connection.conflict + i18n_key=ws.connection.conflict +
         i18n_params={} + message 非空
      2. 发送方向：发往新连接（ws.send），不是旧 owner 的 send_fn
      3. 不下 hello：conflict 是 pending 通知，新端还在等 connection.takeover 决定
    """
    import app.transport.websocket.handler as h_mod
    from app.domain.session import SessionStatus

    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps(
        {"type": "hello", "client_id": "clientB", "locale": "en-US"}))
    # _handshake 返回 True 后进 _loop，需要 ws.receive 是 AsyncMock 才不会被当协程调用。
    # 这里让它模拟「连接断开」：_loop 拿到 disconnect 帧后 break 退出，run 正常结束。
    from starlette.websockets import WebSocketState
    ws.receive = AsyncMock(return_value={"type": "websocket.disconnect", "code": 1000})
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    user = MagicMock()
    user.user_id = "u1"
    monkeypatch.setattr(h_mod, "extract_auth", AsyncMock(return_value=user))

    # state 让 manager.get / start 走通
    state = MagicMock()
    state.session.user_id = "u1"
    state.session.template_id = "t1"
    state.session.template_version = 1
    state.session.consumed_seq = 0
    state.items = []
    state.coverage = {}
    state.status = SessionStatus.SETTING_UP
    state.locale = None
    monkeypatch.setattr(h_mod.manager, "get", AsyncMock(return_value=state))
    monkeypatch.setattr(h_mod.manager, "start", AsyncMock(return_value=state))

    # 关键：旧 owner 仍在 runtime 上（_send_fn 非空 + 不同 client_id）
    existing_owner_send = AsyncMock()
    rt = MagicMock()
    rt._send_fn = existing_owner_send
    rt._bound_client_id = "clientA"   # 与 hello 里的 clientB 不同 → 触发 conflict
    rt.state = state
    rt.ainit = lambda: None
    monkeypatch.setattr(h_mod.registry, "get_or_create", MagicMock(return_value=rt))
    monkeypatch.setattr(h_mod.registry, "is_terminating", lambda sid: False)
    monkeypatch.setattr(h_mod, "get_policy",
                        lambda k: MagicMock(outbound_buffer_size=10, outbound_buffer_ttl_s=60))

    h = WSHandler(ws, "s1")
    await h.run()

    # (2) 旧 owner 不应收到 conflict——它只在后续 connection.takeover 时收到 kicked
    old_conflicts = [c for c in existing_owner_send.call_args_list
                     if c.args and isinstance(c.args[0], dict)
                     and c.args[0].get("type") == "connection.conflict"]
    assert old_conflicts == [], "conflict 帧误发给了旧 owner"

    # (1) 新连接 (ws.send_json) 收到 conflict 帧
    sent_to_new = [call.args[0] for call in ws.send_json.call_args_list
                   if call.args and isinstance(call.args[0], dict)]
    conflict_frames = [m for m in sent_to_new if m.get("type") == "connection.conflict"]
    assert len(conflict_frames) == 1, f"应恰好 1 个 conflict 帧，实际 {len(conflict_frames)}"
    frame = conflict_frames[0]
    assert frame["i18n_key"] == "ws.connection.conflict"
    assert frame["i18n_params"] == {}
    assert frame["message"]  # 非空（向后兼容旧客户端）

    # (3) conflict 是 pending 通知：handler.run 应返回 True 进入 _loop 等 takeover
    # 不应继续发 hello（hello 是 bind 之后才回）
    hello_frames = [m for m in sent_to_new if m.get("type") == "hello"]
    assert hello_frames == [], "pending 端不应收到 hello（hello 等 takeover 后才发）"


async def test_asr_unavailable_frame_carries_i18n_params():
    """PR1: runtime._on_asr_dead 发的 asr_unavailable 帧携带 i18n_params={}。"""
    import app.services.sessions.runtime as rt_mod

    rt = MagicMock()
    rt.state.locale = "en-US"
    rt._asr_dead = False
    sent = []

    async def fake_send(msg):
        sent.append(msg)

    rt._send = fake_send

    # _on_asr_dead 是 async method，但 self 是 MagicMock——
    # 直接调真函数，传入 mock 实例即可（方法内仅用 _send / _asr_dead / state）
    await rt_mod.SessionRuntime._on_asr_dead(rt)
    frames = [m for m in sent if m.get("type") == "error" and m.get("code") == "asr_unavailable"]
    assert len(frames) == 1
    assert frames[0]["i18n_key"] == "ws.asr.disconnected"
    assert frames[0]["i18n_params"] == {}


async def test_audio_low_level_frame_carries_i18n_params():
    """PR1: runtime._on_low_level 发的 audio.low_level 帧携带 i18n_params={}。"""
    from app.adapters.asr.level_monitor import LevelReading
    import app.services.sessions.runtime as rt_mod

    rt = MagicMock()
    rt.state.locale = "en-US"
    sent = []

    async def fake_send(msg):
        sent.append(msg)

    rt._send = fake_send

    reading = LevelReading(p95=-45.0, p10=-60.0, delta=15.0)
    await rt_mod.SessionRuntime._on_low_level(rt, reading)
    frames = [m for m in sent if m.get("type") == "audio.low_level"]
    assert len(frames) == 1
    assert frames[0]["i18n_key"] == "ws.audio.low_level"
    assert frames[0]["i18n_params"] == {}


async def test_bad_handshake_invalid_json_closes_with_4000(monkeypatch):
    """PR2: 客户端首条消息非 JSON → bad_handshake + 关闭码 4000（与文档契约一致）。

    防退化：曾因 _fail 没传 close_code 导致只发帧不关闭，服务端连接悬空。
    """
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value="not-json{")
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    user = MagicMock()
    user.user_id = "u1"
    monkeypatch.setattr(h_mod, "extract_auth", AsyncMock(return_value=user))

    h = WSHandler(ws, "s1")
    await h.run()

    # 1. 发了一帧 bad_handshake
    sent_frames = []
    for c in ws.send_json.call_args_list:
        if not c.args:
            continue
        arg = c.args[0]
        if isinstance(arg, str) and arg.lstrip().startswith("{"):
            sent_frames.append(json.loads(arg))
        elif isinstance(arg, dict):
            sent_frames.append(arg)
    error_frames = [f for f in sent_frames if f.get("type") == "error"]
    assert len(error_frames) == 1
    assert error_frames[0]["code"] == "bad_handshake"

    # 2. 必须以关闭码 4000 关闭（PR2 修复点）
    ws.close.assert_awaited_once()
    assert ws.close.call_args.kwargs["code"] == 4000


async def test_bad_handshake_wrong_type_closes_with_4000(monkeypatch):
    """PR2: 客户端首条消息合法 JSON 但 type != "hello" → bad_handshake + 关闭码 4000。"""
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.scope = {"subprotocols": ["bearer.t"]}
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(return_value=json.dumps({"type": "listen"}))
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    user = MagicMock()
    user.user_id = "u1"
    monkeypatch.setattr(h_mod, "extract_auth", AsyncMock(return_value=user))

    h = WSHandler(ws, "s1")
    await h.run()

    sent_frames = []
    for c in ws.send_json.call_args_list:
        if not c.args:
            continue
        arg = c.args[0]
        if isinstance(arg, str) and arg.lstrip().startswith("{"):
            sent_frames.append(json.loads(arg))
        elif isinstance(arg, dict):
            sent_frames.append(arg)
    error_frames = [f for f in sent_frames if f.get("type") == "error"]
    assert len(error_frames) == 1
    assert error_frames[0]["code"] == "bad_handshake"

    ws.close.assert_awaited_once()
    assert ws.close.call_args.kwargs["code"] == 4000


@pytest.mark.parametrize(
    "non_dict_msg",
    [
        [{"type": "listen"}],   # list
        "hello",                # string
        42,                     # number
        None,                   # null
        True,                   # bool
        [1, 2, 3],              # array
    ],
)
@pytest.mark.asyncio
async def test_dispatch_non_dict_returns_bad_json(monkeypatch, non_dict_msg):
    """post-hello _dispatch 收到非 dict → bad_json + 4411 而不是 ws.internal。

    旧实现 msg.get("type") 在 list 上抛 AttributeError，被 run() 外层
    except Exception 接住走 ws.internal — 把客户端输入错说成服务端 bug。
    复用已有的 code="bad_json"（与 JSONDecodeError 同语义），不再加新
    i18n key。
    """
    import app.transport.websocket.handler as h_mod

    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    h = WSHandler(ws, "sid")
    rt = MagicMock()
    rt._send_fn = h._send
    rt._bound_client_id = "clientA"
    h.runtime = rt

    fail_calls: list = []

    async def fake_fail(ws, state=None, *, code, i18n_key=None, close_code=None, **params):
        fail_calls.append((code, close_code))

    monkeypatch.setattr(h_mod, "_fail", fake_fail)
    await h._dispatch(non_dict_msg)
    assert fail_calls == [("bad_json", 4411)]
