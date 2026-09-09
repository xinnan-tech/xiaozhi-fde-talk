"""REST ignore/skip/unignore/unskip：manager.set_item_status 行为。

不依赖 runtime 存活（会话结束态也可调）；动作仅 mutate set + save_state_auto。
"""
from datetime import datetime, timezone

import pytest
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.runtime import SessionRuntime
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


@pytest.mark.asyncio
async def test_skip_after_ignore_removes_from_ignored():
    tpl = get_template("pm-research")
    s = Session(
        id="s-mutual-1",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-mutual-1", "i1", "ignore")
    await manager.set_item_status("s-mutual-1", "i1", "skip")
    state = await manager.get("s-mutual-1")

    assert state.skipped_ids == {"i1"}
    assert state.ignored_ids == set()


@pytest.mark.asyncio
async def test_ignore_after_skip_removes_from_skipped():
    tpl = get_template("pm-research")
    s = Session(
        id="s-mutual-2",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-mutual-2", "i1", "skip")
    await manager.set_item_status("s-mutual-2", "i1", "ignore")
    state = await manager.get("s-mutual-2")

    assert state.ignored_ids == {"i1"}
    assert state.skipped_ids == set()


@pytest.mark.asyncio
async def test_unskip_does_not_touch_ignored_set():
    """unskip 仅清 skipped_ids；对方集合保持不变。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-mutual-3",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    state.skipped_ids.add("i1")
    state.ignored_ids.add("i1")
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-mutual-3", "i1", "unskip")
    state = await manager.get("s-mutual-3")

    assert "i1" not in state.skipped_ids
    assert "i1" in state.ignored_ids


@pytest.mark.asyncio
async def test_mutual_exclusion_preserves_other_items():
    tpl = get_template("pm-research")
    s = Session(
        id="s-mutual-4",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-mutual-4", "i1", "ignore")
    await manager.set_item_status("s-mutual-4", "i2", "skip")
    await manager.set_item_status("s-mutual-4", "i2", "ignore")
    await manager.set_item_status("s-mutual-4", "i3", "ignore")
    await manager.set_item_status("s-mutual-4", "i3", "skip")
    state = await manager.get("s-mutual-4")

    assert state.ignored_ids == {"i1", "i2"}
    assert state.skipped_ids == {"i3"}


# --- WS 路径覆盖：runtime.skip / runtime.ignore 走同一互斥逻辑 ---

@pytest.mark.asyncio
async def test_runtime_skip_after_ignore_removes_from_ignored():
    """runtime.skip 必须与 manager.set_item_status 一样走 set_item_filtered 互斥。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-rt-mutual-1",
        template_id="pm-research",
        user_id="u-rt-mutual",
        status=SessionStatus.IN_PROGRESS,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    rt = SessionRuntime.__new__(SessionRuntime)
    rt.state = state

    await rt.ignore("i1")
    rt.state = await manager.get("s-rt-mutual-1")
    assert rt.state.ignored_ids == {"i1"}

    await rt.skip("i1")
    rt.state = await manager.get("s-rt-mutual-1")
    assert rt.state.skipped_ids == {"i1"}
    assert rt.state.ignored_ids == set()


@pytest.mark.asyncio
async def test_runtime_ignore_after_skip_removes_from_skipped():
    tpl = get_template("pm-research")
    s = Session(
        id="s-rt-mutual-2",
        template_id="pm-research",
        user_id="u-rt-mutual-2",
        status=SessionStatus.IN_PROGRESS,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    rt = SessionRuntime.__new__(SessionRuntime)
    rt.state = state

    await rt.skip("i1")
    rt.state = await manager.get("s-rt-mutual-2")
    assert rt.state.skipped_ids == {"i1"}

    await rt.ignore("i1")
    rt.state = await manager.get("s-rt-mutual-2")
    assert rt.state.ignored_ids == {"i1"}
    assert rt.state.skipped_ids == set()
