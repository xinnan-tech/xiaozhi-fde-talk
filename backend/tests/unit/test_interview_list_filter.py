"""GET /api/v1/interviews：?status= 过滤。

manager.list_for_user 接受 Optional[list[SessionStatus]] 过滤参数，repo 端用
`.value` 字符串走 SQL `IN` —— 与既有 `count_active` 的字符串过滤口径一致（见
backend/app/persistence/repositories/interview.py::count_active）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.session import Session, SessionStatus
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager


@pytest.mark.asyncio
async def test_list_for_user_filters_by_status():
    # created_at 必须显式设上，save_state 会写 `rec.created_at = s.created_at` 到 NOT NULL 列
    now = datetime.now(timezone.utc)
    sessions = [
        Session(id="s1", template_id="pm-research", user_id="u",
                status=SessionStatus.IN_PROGRESS, created_at=now),
        Session(id="s2", template_id="pm-research", user_id="u",
                status=SessionStatus.ENDED, created_at=now),
        Session(id="s3", template_id="pm-research", user_id="u",
                status=SessionStatus.SUSPENDED, created_at=now),
    ]
    # 通过 repo 落库（直接复用现有 save_state_auto）
    from app.services.sessions.state import SessionState
    from app.services.template.loader import get_template

    for s in sessions:
        tpl = get_template(s.template_id)
        st = SessionState.initial(s, tpl)
        await interview_repo.save_state_auto(st)

    only_in_progress = await manager.list_for_user("u", statuses=[SessionStatus.IN_PROGRESS])
    ids = {s.id for s in only_in_progress}
    assert ids == {"s1"}

    multi = await manager.list_for_user("u", statuses=[SessionStatus.IN_PROGRESS, SessionStatus.SUSPENDED])
    assert {s.id for s in multi} == {"s1", "s3"}
