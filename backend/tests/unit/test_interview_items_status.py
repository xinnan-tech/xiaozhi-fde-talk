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


# --- #202: skip / ignore 在同一 item 上互斥 ---
# 用户连续执行 skip → ignore → unskip 时，若不加互斥：unskip 清掉 skipped_ids，
# 但 ignored_ids 仍含 item，engine 下轮 recompute 会强制把它写成 IGNORED，
# 等同于「用户点 unskip 静默被吞」。本组测试覆盖互斥写入与对称清空。


@pytest.mark.asyncio
async def test_set_item_status_skip_after_ignore_removes_from_ignored():
    """#202: 已 ignore 的 item 再 skip，应从 ignored_ids 里同时清掉。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-202-mutual-1",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-202-mutual-1", "i1", "ignore")
    state = await manager.get("s-202-mutual-1")
    assert "i1" in state.ignored_ids
    assert "i1" not in state.skipped_ids

    await manager.set_item_status("s-202-mutual-1", "i1", "skip")
    state = await manager.get("s-202-mutual-1")
    assert "i1" in state.skipped_ids
    assert "i1" not in state.ignored_ids, (
        "#202: skip 后 ignored_ids 应被同步清空，否则 unskip 会留下隐患"
    )


@pytest.mark.asyncio
async def test_set_item_status_ignore_after_skip_removes_from_skipped():
    """#202 对称路径：先 skip 再 ignore，skipped_ids 必须被清空。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-202-mutual-2",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-202-mutual-2", "i1", "skip")
    state = await manager.get("s-202-mutual-2")
    assert "i1" in state.skipped_ids
    assert "i1" not in state.ignored_ids

    await manager.set_item_status("s-202-mutual-2", "i1", "ignore")
    state = await manager.get("s-202-mutual-2")
    assert "i1" in state.ignored_ids
    assert "i1" not in state.skipped_ids


@pytest.mark.asyncio
async def test_set_item_status_full_repro_from_issue_202():
    """#202 复现路径：skip → ignore → unskip → unignore，engine 不应再把它标 IGNORED。

    修前序列 skip → ignore → unskip：
      - skip 写入 skipped_ids={i1}
      - ignore 写入 ignored_ids={i1}，skipped_ids 留着 {i1}（独立 add）
      - unskip 清 skipped_ids={}，但 ignored_ids 还含 {i1}
      - 下一轮 engine recompute：if-elif 顺序让它强制 status=IGNORED
    修后序列 skip → ignore → unskip → unignore：
      - skip 写入 skipped_ids={i1}，同步清 ignored_ids
      - ignore 写入 ignored_ids={i1}，同步清 skipped_ids（互斥生效）
      - unskip 仅清 skipped_ids（{}）
      - unignore 清 ignored_ids（{}）
      - 两集合都空，engine 看到纯 todo
    """
    tpl = get_template("pm-research")
    s = Session(
        id="s-202-mutual-3",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-202-mutual-3", "i1", "skip")
    state = await manager.get("s-202-mutual-3")
    assert state.skipped_ids == {"i1"}
    assert state.ignored_ids == set(), "skip 时互斥清空 ignored_ids"

    await manager.set_item_status("s-202-mutual-3", "i1", "ignore")
    state = await manager.get("s-202-mutual-3")
    assert state.ignored_ids == {"i1"}
    assert state.skipped_ids == set(), "ignore 时互斥清空 skipped_ids"

    await manager.set_item_status("s-202-mutual-3", "i1", "unskip")
    state = await manager.get("s-202-mutual-3")
    # unskip 是局部 discard：skipped 清掉，但 ignored 不动（用户下一步用 unignore 解锁）
    assert "i1" not in state.skipped_ids
    assert "i1" in state.ignored_ids

    # 用户补一个 unignore 才彻底回到 todo 状态——这就是修后契约：
    # skip/ignore 互斥在「add 路径」保证；undo 路径分开走，需要两步解开
    await manager.set_item_status("s-202-mutual-3", "i1", "unignore")
    state = await manager.get("s-202-mutual-3")
    assert state.skipped_ids == set()
    assert state.ignored_ids == set(), (
        "#202 复现：unskip + unignore 走完后两集合都为空，"
        "engine 不会再把它强制写成 IGNORED"
    )


@pytest.mark.asyncio
async def test_set_item_status_mutual_exclusion_preserves_other_ids():
    """#202 互斥不应误伤别的 item——只清同 id，不动其它 set 成员。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-202-mutual-4",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    # i1 ignored，i2 skipped —— 互斥写入 i2 的 ignore 不应牵连 i1
    await manager.set_item_status("s-202-mutual-4", "i1", "ignore")
    await manager.set_item_status("s-202-mutual-4", "i2", "skip")

    await manager.set_item_status("s-202-mutual-4", "i2", "ignore")
    state = await manager.get("s-202-mutual-4")
    assert state.ignored_ids == {"i1", "i2"}
    assert state.skipped_ids == set()  # 只有 i2 被清，set 应为空

    # 反向：i3 先 ignore 再 skip —— i3 退出 ignored 加入 skipped；i1/i2 不动
    await manager.set_item_status("s-202-mutual-4", "i3", "ignore")
    await manager.set_item_status("s-202-mutual-4", "i3", "skip")
    state = await manager.get("s-202-mutual-4")
    assert state.ignored_ids == {"i1", "i2"}  # i3 已从 ignored 退出
    assert state.skipped_ids == {"i3"}


@pytest.mark.asyncio
async def test_set_item_status_unskip_does_not_clear_ignored():
    """#202 反向：unskip 仍只清 skipped_ids，不动 ignored_ids——单向契约。"""
    tpl = get_template("pm-research")
    s = Session(
        id="s-202-mutual-5",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)

    # 制造「同 item 同时在两集合」的脏状态（绕过 manager），然后调 unskip
    state.skipped_ids.add("i1")
    state.ignored_ids.add("i1")
    await interview_repo.save_state_auto(state)

    await manager.set_item_status("s-202-mutual-5", "i1", "unskip")
    state = await manager.get("s-202-mutual-5")
    assert "i1" not in state.skipped_ids
    # unskip 不动 ignored——这是「互斥只发生在 add 路径」的契约，不双向联动
    assert "i1" in state.ignored_ids
