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


@pytest.fixture(scope="session", autouse=True)
def _ensure_db_schema():
    """dev 自愈：跑所有单测前对真实测试 DB 加缺失列。

    Base.metadata.create_all 只 CREATE TABLE IF NOT EXISTS,不会给已存在的
    interviews 表 ALTER ADD COLUMN。新 ORM 模型加了 keyboard_text /
    handwriting_notes 列后,旧的测试 DB 文件缺这两列,直接 SELECT 会撞
    `no such column: interviews.keyboard_text`。这里调 _ensure_columns
    (idempotent,缺列才 ADD COLUMN)兜住。
    prod 走 alembic upgrade head 自动加,不走本路径。
    """
    try:
        from app.core.settings import get_settings
        from app.persistence.db import engine
        from app.persistence.bootstrap import _ensure_columns
        from app.persistence.models import Base

        url = get_settings().db_url
        if url.startswith("sqlite"):
            db_path = url.split("///", 1)[-1]
            if db_path != ":memory:" and db_path:
                # 文件 SQLite:create_all + _ensure_columns
                async def _run():
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                        await _ensure_columns(conn)
                asyncio.run(_run())
        # 文件非 SQLite(MySQL/PGB):靠 alembic 迁移;不走自愈
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "conftest._ensure_db_schema 跳过:%s: %s",
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


@pytest.fixture
def _reset_handshake_locks():
    """pytest-asyncio auto 模式每个测试一个 event loop，跨 loop 复用 asyncio.Lock
    会 RuntimeError——每个测试清掉一次。

    非 autouse：仅涉及 _handshake / _on_takeover 的测试用 pytestmark.usefixtures
    显式 opt-in，避免侵入与握手锁无关的旧测试。
    """
    from app.services.sessions.manager import manager
    manager._handshake_locks.clear()
    yield
    manager._handshake_locks.clear()
