"""Runtime 状态机并发 cleanup 幂等性。

zombie WS 重连竞态：服务端 keepalive 触发 1011 → 浏览器立即重连，旧 WS 在服务端
仍为 zombie，新 handler 在旧 handler cleanup 之前 bind/listen_start。新 listen_start
撞 LIVE → LIVE 抛 IllegalRuntimeTransition；随后旧 handler cleanup 又撞
SUSPENDED_LOCAL → SUSPENDED_LOCAL。两处都需要 listen_start / unbind 幂等返回 no-op，
不二次抛错。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.services.sessions.runtime import SessionRuntime
from app.services.sessions.state_machine import RuntimeState


def _binds(rt: SessionRuntime) -> None:
    """挂好最小桩，让 listen_start / unbind 走到状态机行。"""
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.pipeline.listen_start = AsyncMock()
    rt.engine.on_unbind = lambda: None
    rt.engine.on_bind = lambda: None
    rt.engine.first_compute = AsyncMock()
    rt.engine.resend_current = AsyncMock()
    rt.engine.on_listen_resume = lambda: None


async def test_listen_start_on_already_live_is_noop(make_state):
    """LIVE → LIVE：服务端仍处于 zombie 状态时新 handler 又收到 listen:start。
    必须幂等返回，不能抛 IllegalRuntimeTransition。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())
    await rt.listen_start()  # 合法：LIVE_PAUSED → LIVE
    assert rt._fsm.state == RuntimeState.LIVE
    pipeline_calls_before = rt.pipeline.listen_start.await_count

    # 第二次 listen:start（旧 WS 还在线时新 WS 又收到 listen:start）
    await rt.listen_start()

    assert rt._fsm.state == RuntimeState.LIVE  # 状态没变
    assert rt.pipeline.listen_start.await_count == pipeline_calls_before  # 不重跑管线


async def test_unbind_when_already_suspended_local_is_noop(make_state):
    """SUSPENDED_LOCAL → SUSPENDED_LOCAL：旧 handler cleanup 在新 handler
    cleanup 之后跑（典型 zombie WS 竞态）。幂等返回，不抛。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())
    await rt.unbind()  # 合法：LIVE_PAUSED → SUSPENDED_LOCAL
    assert rt._fsm.state == RuntimeState.SUSPENDED_LOCAL
    save_calls_before = rt._save_state.await_count
    send_fn_before = rt._send_fn

    # 第二次 unbind（旧 handler 看到 disconnect 后调 cleanup）
    await rt.unbind()

    assert rt._fsm.state == RuntimeState.SUSPENDED_LOCAL  # 没变
    assert rt._save_state.await_count == save_calls_before  # 不重 flush
    assert rt._send_fn is send_fn_before  # 不清空（避免影响新 handler 的 _send）


async def test_unbind_when_already_terminated_is_noop(make_state):
    """TERMINATED → SUSPENDED_LOCAL：end() 后 cleanup 再调 unbind。幂等返回。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())
    await rt.end()  # → TERMINATED
    assert rt._fsm.is_terminated

    await rt.unbind()
    assert rt._fsm.is_terminated  # 不动


async def test_listen_stop_remains_idempotent_for_non_live(make_state):
    """listen_stop 在非 LIVE 状态已幂等（line 137）；守住防回归。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())  # LIVE_PAUSED
    # 不调 listen_start，state == LIVE_PAUSED
    await rt.listen_stop()  # 应当 no-op，不抛
    assert rt._fsm.state == RuntimeState.LIVE_PAUSED


async def test_full_rapid_rebind_cycle_no_illegal_transition(make_state):
    """端到端：bind → listen_start → unbind → 再 bind → 再 listen_start。
    模拟 zombie WS 竞态下重连周期。期间不应抛 IllegalRuntimeTransition。"""
    rt = SessionRuntime(make_state())
    _binds(rt)

    # 第一轮 WS
    await rt.bind(AsyncMock())
    await rt.listen_start()
    await rt.unbind()
    assert rt._fsm.state == RuntimeState.SUSPENDED_LOCAL

    # 第二轮 WS（模拟重连 bind 跑在 unbind 之前的窗口里——这里 unbind 已先跑，
    # 测的是「再次 listen_start 不应崩」）
    await rt.bind(AsyncMock())
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE
    await rt.unbind()
    assert rt._fsm.state == RuntimeState.SUSPENDED_LOCAL


# ── 复用并发安全：zombie handler 的迟到 cleanup 不得踩坏新连接 ──────────────

async def test_stale_handler_unbind_does_not_clobber_new_binding(make_state):
    """WS1 bind+listen_start 后 LIVE；WS2 抢先 bind（runtime 仍 live，zombie 竞态）。
    WS1 迟到的 unbind(自己的 send) 必须整体 no-op——不能把 WS2 的 _send_fn 抹 None、
    也不能把 FSM 拉回 suspended_local（否则 WS2 握着活 ASR 却收发全废）。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    send1, send2 = AsyncMock(), AsyncMock()

    await rt.bind(send1)
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE

    # WS2 在 WS1 unbind 之前 bind（runtime 仍 live，zombie 竞态）
    await rt.bind(send2)
    assert rt._send_fn is send2                   # ownership：新 send_fn 已接管
    assert rt._fsm.state == RuntimeState.LIVE_PAUSED  # 回到待 listen（不再遗留 LIVE）

    # WS1 迟到的 cleanup —— 必须是 no-op（不能踩坏 WS2）
    result = await rt.unbind(send1)
    assert result is False                        # 未拆绑
    assert rt._send_fn is send2                   # 没被抹掉
    assert rt._fsm.state == RuntimeState.LIVE_PAUSED  # 没被拉回 suspended

    # WS2 仍能正常驱动 runtime（幂等 listen_start）
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE


async def test_unbind_aborts_when_superseded_during_flush(make_state):
    """check-then-await-then-act 漏洞：unbind 通过 ownership 检查后 await _force_flush，
    该 await 窗口里新 handler 抢先 bind 覆盖了 _send_fn。flush 返回后必须复查 ownership——
    不再是 owner 就整体 no-op（返回 False），否则会 null 掉新 handler 的 _send_fn 并把
    FSM 拉回 suspended_local，新连接即刻收发全废。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    send1, send2 = AsyncMock(), AsyncMock()
    await rt.bind(send1)

    # 模拟 flush 的 await 窗口内新 handler bind：_force_flush 副作用 = bind(send2)
    async def _flush_then_rebind():
        await rt.bind(send2)
    rt._force_flush = AsyncMock(side_effect=_flush_then_rebind)

    result = await rt.unbind(send1)
    assert result is False                                  # 被取代，未拆绑
    assert rt._send_fn is send2                             # 新 handler 绑定完好
    assert rt._fsm.state is not RuntimeState.SUSPENDED_LOCAL  # 没被拉回 suspended


async def test_unbind_returns_true_when_genuinely_owner(make_state):
    """正常断连（无竞态）：unbind 是当前 owner，应真正拆绑并返回 True。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())
    result = await rt.unbind()
    assert result is True
    assert rt._fsm.state == RuntimeState.SUSPENDED_LOCAL
    assert rt._send_fn is None


async def test_listen_start_rebuilds_when_asr_dead_even_if_live(make_state):
    """FSM 已 LIVE 但 _asr_dead（旧管线死了）时，listen_start 必须重建管线，
    不能因幂等守卫直接返回——否则重连复用了一条死 ASR，永远不出字。"""
    rt = SessionRuntime(make_state())
    _binds(rt)
    await rt.bind(AsyncMock())
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE
    rebuilds_before = rt.pipeline.listen_start.await_count

    rt._asr_dead = True  # 模拟旧 ASR 连接已死
    await rt.listen_start()
    assert rt.pipeline.listen_start.await_count == rebuilds_before + 1  # 重建了
    assert rt._asr_dead is False


async def test_terminated_runtime_not_reused_on_reconnect(make_state):
    """TERMINATED 的 runtime 不能被 get_or_create 复用，park 也不能寄存它——
    否则重连取回 terminated runtime，listen_start 撞 terminated→live 崩。"""
    from app.services.sessions.runtime import RuntimeRegistry
    reg = RuntimeRegistry()
    state = make_state()

    rt1 = reg.get_or_create("s1", state)
    rt1.pipeline.flush = AsyncMock()
    rt1.pipeline.close = AsyncMock()
    rt1.engine.on_end = AsyncMock()
    rt1._save_state = AsyncMock()
    await rt1.end()
    assert rt1._fsm.is_terminated

    # park 拒绝寄存 terminated
    reg.park("s1", rt1, ttl_s=60)
    assert "s1" not in reg._parked
    assert "s1" not in reg._active

    # get_or_create 即便在 _active 遇到 terminated，也必须替换为全新 runtime
    reg._active["s1"] = rt1
    rt2 = reg.get_or_create("s1", state)
    assert rt2 is not rt1
    assert not rt2._fsm.is_terminated
    assert reg._active["s1"] is rt2


# ── zombie LIVE 重连后「音频进得来却不出字」 ──────────────────────────

async def test_zombie_live_bind_recycles_asr_and_returns_to_live_paused(make_state, monkeypatch):
    """旧连接未及 unbind、新连接抢先 bind（zombie 竞态），runtime 仍处 LIVE。

    用户实测：重连后 WS 持续传音频，却永远不出字。两个根因，bind 必须同时处理：
      1) 遗留 LIVE 态让 listen_start 幂等早退 → ASR 管线不重建；
      2) 旧 ASR provider「假活」（WS 仍开但 FunASR 2pass 会话卡死、不再出字），
         is_alive 区分不出，复用会带病上岗。
    修复：bind 回到 live_paused + 拆除旧 provider，让客户端 listen:start 建全新的。
    解码器保留（MediaRecorder 是连续 WebM 流，重连不重发 EBML 头）。
    """
    import app.services.sessions.pipeline as pl_mod
    from app.services.sessions.runtime import SessionRuntime
    from app.services.sessions.state_machine import RuntimeState

    rt = SessionRuntime(make_state())
    # 不 mock pipeline.listen_start——要验证 provider 真的被重建；只 stub 引擎 + 落盘
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_bind = lambda: None
    rt.engine.first_compute = AsyncMock()
    rt.engine.resend_current = AsyncMock()
    rt.engine.on_listen_resume = lambda: None

    created = []

    def _fake_provider():
        m = MagicMock()
        m.start_stream = AsyncMock()
        m.force_close = AsyncMock()
        m.is_alive = True
        created.append(m)
        return m

    monkeypatch.setattr(pl_mod, "create_asr_provider", _fake_provider)

    # 第一条连接：bind + listen:start → LIVE，建起 provider#0
    await rt.bind(AsyncMock())
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE
    assert len(created) == 1
    stale = created[-1]
    assert rt.pipeline._stream_provider is stale

    # zombie：新连接在旧 handler unbind 之前 bind（runtime 仍 LIVE，_send_fn 非空）
    await rt.bind(AsyncMock())
    assert rt._fsm.state == RuntimeState.LIVE_PAUSED        # 不再遗留 LIVE
    assert rt.pipeline._stream_provider is None             # 旧 provider 已拆除
    stale.force_close.assert_awaited_once()                 # 立即拆除（不等 5s 收尾）

    # 客户端 listen:start → 建全新 provider，不复用 stale
    await rt.listen_start()
    assert rt._fsm.state == RuntimeState.LIVE
    assert len(created) == 2
    assert rt.pipeline._stream_provider is created[-1]
    assert rt.pipeline._stream_provider is not stale