from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock


async def test_sweep_all_in_progress_to_suspended(monkeypatch):
    """强杀兜底：所有 in_progress（不论 started_at）都转 suspended。

    优雅关闭时 shutdown_quick 已转 suspended；sweep 兜底强杀（kill -9 / Ctrl+C
    两次）场景——那时 shutdown_quick 没跑，DB 卡 in_progress。不再按 started_at
    过滤：刚开不久的会话强杀后同样卡住，也该转 suspended（转写由前端重建 recorder
    兜底）。
    """
    from app.domain.session import SessionStatus

    now = datetime.now(timezone.utc)
    recent = MagicMock()
    recent.status = SessionStatus.IN_PROGRESS.value
    recent.started_at = now - timedelta(seconds=10)
    stale = MagicMock()
    stale.status = SessionStatus.IN_PROGRESS.value
    stale.started_at = now - timedelta(seconds=600)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [recent, stale]
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    import app.persistence.bootstrap as b

    monkeypatch.setattr(b, "SessionLocal", lambda: session)
    n = await b.sweep_stale_sessions()
    assert n == 2  # 都被扫（不再按时间过滤）
    assert recent.status == SessionStatus.SUSPENDED.value
    assert stale.status == SessionStatus.SUSPENDED.value
