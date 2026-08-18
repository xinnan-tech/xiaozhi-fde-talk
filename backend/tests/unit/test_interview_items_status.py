"""REST ignore/skip/unignore/unskip：manager.set_item_status 行为。

不依赖 runtime 存活（会话结束态也可调）；动作仅 mutate set + save_state_auto。
"""
from datetime import datetime, timezone

import pytest
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template
from app.domain.session import Session, SessionStatus


@pytest.mark.asyncio
async def test_set_item_status_ignore_and_unignore():
    tpl = get_template("pm-research")
    s = Session(
        id="s-item-1",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-item-1", "i1", "ignore")
    state = await manager.get("s-item-1")
    assert "i1" in state.ignored_ids

    await manager.set_item_status("s-item-1", "i1", "unignore")
    state = await manager.get("s-item-1")
    assert "i1" not in state.ignored_ids


@pytest.mark.asyncio
async def test_set_item_status_skip_and_unskip():
    tpl = get_template("pm-research")
    s = Session(
        id="s-item-2",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-item-2", "i1", "skip")
    state = await manager.get("s-item-2")
    assert "i1" in state.skipped_ids

    await manager.set_item_status("s-item-2", "i1", "unskip")
    state = await manager.get("s-item-2")
    assert "i1" not in state.skipped_ids


@pytest.mark.asyncio
async def test_set_item_status_invalid_action():
    with pytest.raises(ValueError):
        await manager.set_item_status("any", "i1", "bogus")
