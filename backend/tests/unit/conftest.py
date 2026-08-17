"""单元测试公共 fixture：会话/段工厂。

不依赖任何外部服务，可纯离线运行（CI 必跑）。
"""
from __future__ import annotations

import asyncio

import pytest

from app.domain.session import Session, TranscriptSegment
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


@pytest.fixture
def make_state():
    """构造一个 pm-research 模板的初始 SessionState。"""
    def _make(goal: str = "做个需求管理工具") -> SessionState:
        tpl = get_template("pm-research")
        session = Session(
            id="test-session-1",
            template_id="pm-research",
            goal=goal,
            status="in_progress",
        )
        return SessionState.initial(session, tpl)
    return _make


@pytest.fixture
def make_seg():
    def _make(seg_id: str, text: str) -> TranscriptSegment:
        return TranscriptSegment(seg_id=seg_id, start_ms=0, text=text, final=True)
    return _make


@pytest.fixture
def wait_for_tasks():
    async def _wait() -> None:
        await asyncio.sleep(0.15)
    return _wait
