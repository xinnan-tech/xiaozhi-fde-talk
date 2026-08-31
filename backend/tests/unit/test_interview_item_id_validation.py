"""#164：skip / ignore 接口传入非法 item_id 必须 404，不污染 DB。

两层契约：
1. `manager.set_item_status(..., valid_ids=...)` 收到合法集合时，skip/ignore
   写入若 item_id ∉ valid_ids → 抛 I18nError(HTTP_COACHING_ITEM_NOT_FOUND, 404)。
   unskip/unignore 是 idempotent discard，传与不传 valid_ids 都放过。
2. 路由 `POST /items/{bad_id}/skip` 与 `/ignore` 必须把模板快照的 must_ask[].id
   集合透传给 manager——这一步把「内部豁免」与「外部契约」对齐。

不在本测范围：HTTP 层完整 happy path 路由（已有 FastAPI TestClient 用例覆盖
set_item_status 直接调用即可断 manager/契约；HTTP 集成交给 e2e / 现有路由测试）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.session import Session, SessionStatus
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


VALID = {"objective", "pain", "current_solution", "constraints", "decision", "success"}


async def _make_state(sid: str, *, template_id: str = "pm-research") -> SessionState:
    tpl = get_template(template_id)
    s = Session(
        id=sid,
        template_id=template_id,
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
        # 模拟真实创建流程固化模板快照（manager.create 时设；本测关心 valid_ids 校验，
        # 让 session 与「正常创建」状态对齐）
        template_snapshot=tpl.model_dump(mode="json"),
    )
    state = SessionState.initial(s, tpl)
    await interview_repo.save_state_auto(state)
    return state


# ────────────── manager：valid_ids 校验 ──────────────


@pytest.mark.asyncio
async def test_skip_with_valid_ids_rejects_unknown_id():
    """valid_ids 给出时，skip 一个不存在的 id → 404 I18nError，不写 DB。"""
    await _make_state("s-164-1")
    with pytest.raises(I18nError) as exc_info:
        await manager.set_item_status("s-164-1", "fake-id-xxx", "skip", valid_ids=VALID)
    assert exc_info.value.http_status == 404
    assert exc_info.value.code == Keys.HTTP_COACHING_ITEM_NOT_FOUND.value
    assert exc_info.value.params.get("item_id") == "fake-id-xxx"
    # 关键：DB 里 skipped_ids 没被污染
    state = await manager.get("s-164-1")
    assert "fake-id-xxx" not in state.skipped_ids
    assert state.skipped_ids == set()


@pytest.mark.asyncio
async def test_ignore_with_valid_ids_rejects_unknown_id():
    """valid_ids 给出时，ignore 一个不存在的 id → 404 I18nError，不写 DB。"""
    await _make_state("s-164-2")
    with pytest.raises(I18nError) as exc_info:
        await manager.set_item_status("s-164-2", "another-fake", "ignore", valid_ids=VALID)
    assert exc_info.value.http_status == 404
    state = await manager.get("s-164-2")
    assert "another-fake" not in state.ignored_ids
    assert state.ignored_ids == set()


@pytest.mark.asyncio
async def test_skip_accepts_real_must_ask_id():
    """真实 must_ask.id 在 valid_ids 里 → skip 成功。"""
    await _make_state("s-164-3")
    await manager.set_item_status("s-164-3", "objective", "skip", valid_ids=VALID)
    state = await manager.get("s-164-3")
    assert "objective" in state.skipped_ids


@pytest.mark.asyncio
async def test_ignore_accepts_real_must_ask_id():
    """真实 must_ask.id 在 valid_ids 里 → ignore 成功。"""
    await _make_state("s-164-4")
    await manager.set_item_status("s-164-4", "pain", "ignore", valid_ids=VALID)
    state = await manager.get("s-164-4")
    assert "pain" in state.ignored_ids


@pytest.mark.asyncio
async def test_unskip_ignores_valid_ids():
    """unskip 是 idempotent discard——传 valid_ids 也放过错 id（discard 本就静默）。"""
    await _make_state("s-164-5")
    # valid_ids=VALID 含 objective；unskip 一个不存在的 id 不报错
    await manager.set_item_status("s-164-5", "never-was-there", "unskip", valid_ids=VALID)
    # state 没新增 skipped_ids
    state = await manager.get("s-164-5")
    assert state.skipped_ids == set()


@pytest.mark.asyncio
async def test_unignore_ignores_valid_ids():
    """unignore 是 idempotent discard——传 valid_ids 也放过错 id。"""
    await _make_state("s-164-6")
    await manager.set_item_status("s-164-6", "never-was-there", "unignore", valid_ids=VALID)
    state = await manager.get("s-164-6")
    assert state.ignored_ids == set()


@pytest.mark.asyncio
async def test_skip_without_valid_ids_keeps_legacy_permissive_behavior():
    """valid_ids=None（未传）→ 保留历史宽松行为：内部路径不校验。

    内部 runtime.ignore / runtime.skip 仍走这条路径（route 不在它们的
    调用链上），保留豁免避免破坏既有契约。
    """
    await _make_state("s-164-7")
    # 不传 valid_ids → 不校验 → 写入成功
    await manager.set_item_status("s-164-7", "internal-bypass", "skip")
    state = await manager.get("s-164-7")
    assert "internal-bypass" in state.skipped_ids


@pytest.mark.asyncio
async def test_skip_with_empty_valid_ids_rejects_everything():
    """valid_ids=set() → 任何 id 都被拒（404）；空集合本身合法。"""
    await _make_state("s-164-8")
    with pytest.raises(I18nError) as exc_info:
        await manager.set_item_status("s-164-8", "objective", "skip", valid_ids=set())
    assert exc_info.value.http_status == 404
    state = await manager.get("s-164-8")
    assert "objective" not in state.skipped_ids


# ────────────── 路由层：valid_ids 透传自模板快照 ──────────────


def _build_user_override(user_id: str):
    """构造一个 get_current_user override，返 fake CurrentUser（不走 Bearer token）。"""
    from app.domain.auth import CurrentUser
    from app.transport.http.dependencies import get_current_user

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id=user_id, role="user", username=user_id)

    return get_current_user, _fake_user


def test_route_ignore_passes_snapshot_must_ask_ids_as_valid_set(monkeypatch):
    """白盒：TestClient 真 POST /items/{id}/ignore，monkeypatch 抓 manager 收到的 valid_ids。

    验证 routes/interviews.py ignore_item handler 把 `template_snapshot` 派生的合法
    id 集合透传给 manager.set_item_status。如果路由里漏掉 `valid_ids=_valid_item_ids(state)`，
    本测试会抓到 valid_ids=None 而 fail。
    """
    import asyncio
    from fastapi.testclient import TestClient

    from app.app import create_app

    async def _setup():
        await _make_state("s-164-9")

    asyncio.get_event_loop().run_until_complete(_setup())

    captured = {}

    async def _fake_set(session_id, item_id, action, valid_ids=None):
        captured["session_id"] = session_id
        captured["item_id"] = item_id
        captured["action"] = action
        captured["valid_ids"] = valid_ids
        # 走真实 repo 写回 state
        state = await manager.get(session_id)
        if action == "ignore":
            state.ignored_ids.add(item_id)
            from app.persistence.repositories.interview import interview_repo
            await interview_repo.save_state_auto(state)
        return state

    monkeypatch.setattr(manager, "set_item_status", _fake_set)

    app = create_app()
    dep, fake_user = _build_user_override("u")
    app.dependency_overrides[dep] = fake_user

    client = TestClient(app)
    r = client.post("/api/v1/interviews/s-164-9/items/objective/ignore")

    assert r.status_code == 200, r.text
    # 关键断言：handler 把模板快照的 must_ask[].id 集合透传给 manager
    assert captured["valid_ids"] == VALID
    assert captured["action"] == "ignore"
    assert captured["item_id"] == "objective"


def test_route_skip_passes_snapshot_must_ask_ids_as_valid_set(monkeypatch):
    """同上，POST /items/{id}/skip：路由必须把 valid_ids 透传给 manager。"""
    import asyncio
    from fastapi.testclient import TestClient

    from app.app import create_app

    async def _setup():
        await _make_state("s-164-10")

    asyncio.get_event_loop().run_until_complete(_setup())

    captured = {}

    async def _fake_set(session_id, item_id, action, valid_ids=None):
        captured["valid_ids"] = valid_ids
        captured["action"] = action
        state = await manager.get(session_id)
        if action == "skip":
            state.skipped_ids.add(item_id)
            from app.persistence.repositories.interview import interview_repo
            await interview_repo.save_state_auto(state)
        return state

    monkeypatch.setattr(manager, "set_item_status", _fake_set)

    app = create_app()
    dep, fake_user = _build_user_override("u")
    app.dependency_overrides[dep] = fake_user

    client = TestClient(app)
    r = client.post("/api/v1/interviews/s-164-10/items/pain/skip")

    assert r.status_code == 200, r.text
    assert captured["valid_ids"] == VALID
    assert captured["action"] == "skip"


def test_route_valid_item_ids_returns_none_when_snapshot_empty():
    """legacy 访谈（snapshot 为空）→ _valid_item_ids 返 None，不走当前模板回退。

    这是 P1.1 修的契约：旧访谈创建于本 PR 之前，snapshot 为空；admin 编辑当前模板
    删/加 must_ask 时，旧访谈的合法集合必须保持原样（既不误报 404 也不误接受），
    所以返 None 让 manager 跳过校验——而非用当前模板集合偷换。
    """
    from datetime import datetime, timezone
    from app.domain.session import Session, SessionStatus
    from app.services.sessions.state import SessionState
    from app.services.template.loader import get_template
    from app.transport.http.routes.interviews import _valid_item_ids

    s = Session(
        id="s-164-legacy",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
        # template_snapshot=None → legacy
    )
    tpl = get_template("pm-research")
    state = SessionState.initial(s, tpl)
    assert state.session.template_snapshot is None

    assert _valid_item_ids(state) is None


def test_route_valid_item_ids_returns_none_when_snapshot_corrupted():
    """template_snapshot 是损坏 dict（缺必填字段）→ _valid_item_ids 返 None。

    验证：catch Template(**snap) 抛 ValidationError 时返回 None 而非 fallback 到
    当前模板——immutability 契约要求旧访谈保留自己创建时的合法集合。
    """
    from datetime import datetime, timezone
    from app.domain.session import Session, SessionStatus
    from app.services.sessions.state import SessionState
    from app.services.template.loader import get_template
    from app.transport.http.routes.interviews import _valid_item_ids

    s = Session(
        id="s-164-corrupt",
        template_id="pm-research",
        user_id="u",
        status=SessionStatus.ENDED,
        created_at=datetime.now(timezone.utc),
        template_snapshot={"version": "1"},  # 缺 coaching / id 等必填
    )
    tpl = get_template("pm-research")
    state = SessionState.initial(s, tpl)

    assert _valid_item_ids(state) is None
