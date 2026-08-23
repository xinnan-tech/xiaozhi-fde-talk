"""WebSocket 协议 server 帧契约测试。

`docs/websocket-protocol.md` 承诺了若干 server 帧（connection.kicked /
session.ended / session.suspended / audio.low_level）。本测试把它们汇总到
一处作为「协议契约」：每次新增 server→client 帧时，把断言追加到这里，
避免散落在多个测试里、协议文档 vs 实际行为出现静默 drift。

具体场景的细粒度断言仍在各自专项测试里（test_takeover_protocol /
test_end_closes_ws / test_hardening.test_suspend_* / test_low_level_frame）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.asr.level_monitor import LevelReading
from app.core.i18n import Keys, t
from app.services.sessions.runtime import SessionRuntime


# 文档承诺的 server 帧全集（与 docs/websocket-protocol.md §5.2 对齐）
PROMISED_SERVER_FRAMES = {
    "hello",
    "connection.conflict",
    "connection.kicked",
    "asr",
    "coaching.update",
    "session.ended",
    "session.suspended",
    "audio.low_level",
    "error",
}


def _stub_runtime(state) -> SessionRuntime:
    """挂最小桩：engine/pipeline 不触网不落盘，只验出站帧。"""
    rt = SessionRuntime(state)
    rt.engine = MagicMock()
    rt.engine.on_end = AsyncMock()
    rt.engine.on_unbind = lambda: None
    rt.pipeline = MagicMock()
    rt.pipeline.flush = AsyncMock()
    rt.pipeline.close = AsyncMock()
    rt._force_flush = AsyncMock()
    rt._save_state = AsyncMock()
    rt.pipeline.listen_start = AsyncMock()
    rt.pipeline.reset_provider = AsyncMock()
    rt.engine.on_bind = lambda: None
    rt.engine.first_compute = AsyncMock()
    rt.engine.resend_current = AsyncMock()
    rt.engine.on_listen_resume = lambda: None
    return rt


def _sent(send_mock) -> list[dict]:
    return [c.args[0] for c in send_mock.call_args_list if c.args]


# ---- connection.kicked：接管路径（runtime.takeover） ----


async def test_takeover_sends_connection_kicked(make_state):
    rt = _stub_runtime(make_state())
    send_old, evict_old = AsyncMock(), AsyncMock()
    await rt.bind(send_old, "clientA", evict_old)

    sent_kicked = []
    send_old.side_effect = lambda m: sent_kicked.append(m)

    await rt.takeover(AsyncMock(), "clientB", AsyncMock())
    types = [m.get("type") for m in _sent(send_old)]
    assert "connection.kicked" in types
    kicked = next(m for m in _sent(send_old) if m.get("type") == "connection.kicked")
    # 文档 §5.2 字段：reason (string)；实现附带 i18n 字段便于前端用 vue-i18n 渲染
    assert isinstance(kicked["reason"], str) and kicked["reason"]
    assert kicked["i18n_key"] == Keys.WS_CONNECTION_KICKED.value


# ---- session.ended：end 路径（runtime.end） ----


async def test_end_sends_session_ended(make_state):
    rt = _stub_runtime(make_state())
    sent, evicted = [], []
    rt._send_fn = AsyncMock(side_effect=lambda m: sent.append(m))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.end()
    types = [m.get("type") for m in sent]
    assert "session.ended" in types
    assert evicted == [(4406, t(Keys.WS_CLOSE_SESSION_ENDED.value, locale=rt.state.locale))]


# ---- session.suspended：挂起路径（runtime.suspend） ----


async def test_suspend_sends_session_suspended(make_state):
    rt = _stub_runtime(make_state())
    sent, evicted = [], []
    rt._send_fn = AsyncMock(side_effect=lambda m: sent.append(m))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.suspend()
    types = [m.get("type") for m in sent]
    assert "session.suspended" in types
    assert "session.ended" not in types  # 互斥：suspended 可继续，ended 不可继续
    assert evicted == [(4403, t(Keys.WS_CLOSE_SUSPENDED.value, locale=rt.state.locale))]


# ---- audio.low_level：电平监测路径（runtime._on_low_level） ----


async def test_low_level_sends_audio_low_level(make_state):
    rt = _stub_runtime(make_state())
    rt._send_fn = AsyncMock()
    await rt._on_low_level(LevelReading(-57.3, -82.1, 24.8))
    rt._send_fn.assert_awaited_once()
    frame = rt._send_fn.call_args.args[0]
    assert frame["type"] == "audio.low_level"
    # 文档 §5.2 字段：dbfs (number) / message (string)
    assert isinstance(frame["dbfs"], (int, float))
    assert frame["i18n_key"] == Keys.WS_AUDIO_LOW_LEVEL.value


# ---- 协议契约：所有承诺的 server 帧至少在一处代码路径有定义 ----


def test_promised_frames_have_at_least_one_producer():
    """PROMISED_SERVER_FRAMES 里每一帧都至少有一个 _send({"type": ...}) 调用点。

    这是文档与实现的契约闸：哪天有人删掉 _send(...) 调用但忘了改文档，
    本测试会报警。hello/asr/coaching.update/connection.conflict/error 不在
    本测试覆盖范围——它们的发送路径分布在 transport 层多处、专项断言更细。
    """
    import inspect

    from app.services.sessions import runtime

    src = inspect.getsource(runtime)
    # 这四帧必须出现在 runtime.py 里（其余帧由 transport/handler 等模块产出）
    for frame in ("connection.kicked", "session.ended", "session.suspended", "audio.low_level"):
        assert f'"type": "{frame}"' in src, (
            f"协议承诺的 server 帧 {frame!r} 在 runtime.py 已找不到 _send 调用点，"
            "如确认要删除，请同时更新 docs/websocket-protocol.md §5.2 与本测试。"
        )


@pytest.mark.parametrize("frame", sorted(PROMISED_SERVER_FRAMES))
def test_promised_frame_appears_in_protocol_doc(frame):
    """PROMISED_SERVER_FRAMES 里的每一帧都必须出现在 docs/websocket-protocol.md。

    反向契约：协议文档里若新增了某帧的实现，必须同步加入本集合；删实现则
    必须同步从文档删除。这一对双向断言把「文档 vs 实现」漂移显式化。
    """
    import pathlib

    # pytest 工作目录是 backend/，docs/ 在项目根；上溯到仓根
    # parents[0]=unit [1]=tests [2]=backend [3]=repo
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    doc = (repo_root / "docs" / "websocket-protocol.md").read_text(encoding="utf-8")
    # 文档用 `` `frame.type` `` 反引号包裹帧名；用最宽松的子串匹配
    assert frame in doc, f"协议文档里找不到 server 帧 {frame!r} 的定义"