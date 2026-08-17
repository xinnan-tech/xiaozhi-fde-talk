"""engine.first_generate：首评生成——幂等、锁内复查、失败保种子、顺序化 priority。"""
from __future__ import annotations

from unittest.mock import AsyncMock

from app.adapters.llm.base import LLMError
from app.domain.session import SessionStatus
from app.services.coaching.engine import CoachingEngine

_PAYLOAD = {"items": [
    {"id": "objective", "text": "定制版目标问题", "status": "todo"},
    {"id": None, "text": "新定制问题", "status": "todo"},
]}


def _engine(make_state, payload=_PAYLOAD):
    sent = []

    async def send(msg):
        sent.append(msg)

    engine = CoachingEngine(make_state(), send)
    engine._llm = AsyncMock()
    engine._llm.chat_json.return_value = payload
    # _llm_with_timeout 经 _get_llm() 现取工厂单例、不读 self._llm（P2-3），
    # 须按既有测试惯例（test_engine.py:102 等 6 处）把入口指回 mock，否则打到真实 LLM
    engine._get_llm = lambda: engine._llm
    engine._persist = AsyncMock()
    return engine, sent


async def test_first_generate_replaces_seed(make_state):
    engine, sent = _engine(make_state)
    await engine.first_generate()
    assert engine.state.session.first_batch_generated is True
    assert [it.text for it in engine.state.items] == ["定制版目标问题", "新定制问题"]
    assert [it.priority for it in engine.state.items] == [1, 2]  # 输出顺序即发问顺序
    engine._persist.assert_awaited_once()
    assert [m["phase"] for m in sent] == ["recomputing", "final"]
    assert sent[1]["version"] == 1 and len(sent[1]["items"]) == 2


async def test_first_generate_skips_when_flag_set(make_state):
    engine, sent = _engine(make_state)
    engine.state.session.first_batch_generated = True
    await engine.first_generate()
    engine._llm.chat_json.assert_not_awaited()
    assert sent == []


async def test_first_generate_skips_when_transcript_started(make_state, make_seg):
    engine, sent = _engine(make_state)
    engine.state.transcript.append(make_seg("s1", "已经聊上了"))
    await engine.first_generate()
    engine._llm.chat_json.assert_not_awaited()
    assert sent == []


async def test_first_generate_llm_error_keeps_seed(make_state):
    engine, sent = _engine(make_state)
    engine._llm.chat_json.side_effect = LLMError("provider down")
    await engine.first_generate()
    assert engine.state.session.first_batch_generated is False
    assert len(engine.state.items) == 6            # 模板种子原样
    assert [m["phase"] for m in sent] == ["recomputing", "final"]
    assert len(sent[1]["items"]) == 6


async def test_first_generate_skips_terminal_status(make_state):
    engine, sent = _engine(make_state)
    engine.state.session.status = SessionStatus.ENDED
    await engine.first_generate()
    engine._llm.chat_json.assert_not_awaited()
    assert sent == []


async def test_first_compute_kicks_first_generate(make_state, wait_for_tasks):
    engine, sent = _engine(make_state)
    await engine.first_compute()
    assert sent[0]["phase"] == "final" and len(sent[0]["items"]) == 6  # 种子先推
    await wait_for_tasks()
    assert engine.state.session.first_batch_generated is True
    assert sent[-1]["phase"] == "final" and len(sent[-1]["items"]) == 2


async def test_first_compute_no_kick_when_generated(make_state, wait_for_tasks):
    engine, sent = _engine(make_state)
    engine.state.session.first_batch_generated = True
    await engine.first_compute()
    await wait_for_tasks()
    engine._llm.chat_json.assert_not_awaited()
    assert len(sent) == 1


async def test_resend_current_kicks_pending_first_generate(make_state, wait_for_tasks):
    """重连复用路径：寄存期间 PATCH 实际变更清了 flag（_refresh 刷进 runtime.state）→
    snapshot 推完后同样补跑，不把旧目标的清单一直挂着。"""
    engine, sent = _engine(make_state)
    engine.state.session.first_batch_generated = True
    await engine.first_compute()                        # 首绑：flag 已置，无补跑
    engine.state.session.first_batch_generated = False  # 模拟 PATCH + _refresh 后的重连
    await engine.resend_current()                       # 重连 snapshot（version 不变）
    await wait_for_tasks()
    assert engine.state.session.first_batch_generated is True
    assert sent[-1]["phase"] == "final" and len(sent[-1]["items"]) == 2
