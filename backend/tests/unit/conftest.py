"""单元测试公共 fixture：会话/段工厂。

不依赖任何外部服务，可纯离线运行（CI 必跑）。
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from app.domain.session import Session, TranscriptSegment
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session", autouse=True)
def _warm_templates():
    """模板 DB 化后，无 lifespan 的纯单测也需要缓存里有模板（原文件加载是惰性的）。

    仅 warm「需要模板的测试」——其他测试（如 test_password_policy）若 DB 未就绪，
    warm 自身会抛 DataError / OperationalError，把错误位置甩到 conftest 难以定位。
    这里 catch 后降级为「缓存未 warm」，需要模板的测试用 _lifespan_app 自管 warm。
    """
    try:
        from app.services.template import loader
        asyncio.run(loader.warm())
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "conftest._warm_templates 跳过：DB 未就绪或 warm 失败（%s：%s）",
            type(e).__name__, e,
        )


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
