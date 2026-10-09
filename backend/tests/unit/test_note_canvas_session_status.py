"""笔记 + 画板 POST 状态机校验(仅 in_progress)。

保护契约:
- POST /notes/keyboard、/notes/handwriting、/canvases/{idx} 必须 in_progress
- 其他状态(SUSPENDED / CREATED / SETTING_UP / ENDED / EXTRACTING / DONE)→ 409 + WS_SESSION_ENDED
- DELETE /canvases/{idx} 不校验状态机(handler 用 manager.get 直返)
- DELETE /notes/handwriting/{image_id} 笔记路径仍走 _load_session_for_note,
  即仅 in_progress(与笔记 POST 共享同一状态机)

回归需求:#state-allow-must-be-in-progress-only
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.i18n.messages import Keys
from app.domain.auth import CurrentUser
from app.domain.session import SessionStatus
from app.transport.http.dependencies import get_current_user


def _current_user():
    return CurrentUser(user_id="u1", username="u1", role="user")


def _session_state(status: SessionStatus):
    """构造 SimpleNamespace 模拟 SessionState,让 _load_session_for_note 通过。"""
    return SimpleNamespace(
        session=SimpleNamespace(
            id="s1",
            user_id="u1",
            status=status,
            template_id="pm-research",
            template_version="1",
            template_snapshot=None,
            base_info={},
            goal="g",
            first_batch_generated=False,
            consumed_seq=0,
            created_at=None,
            started_at=None,
            ended_at=None,
        ),
        transcript=[],
        items=[],
        skipped_ids=set(),
        ignored_ids=set(),
        coverage={},
        keyboard_text=None,
        handwriting_notes=[],
    )


# ---- 笔记 POST 状态机 ----

@pytest.fixture
def make_status_client():
    """返回 (TestClient)——内部用 patch 启动 manager + interview_repo。

    delete/list_canvases 走 DB 读,同步 mock interview_repo.get_state_auto。
    注意:start() 返回的是 mock 替身,unpatch 必须保存 patcher 对象本身
    调 stop()——对替身调 stop() 是 no-op,patch 泄漏会污染后续测试。
    """
    from app.app import create_app

    patchers = []

    def _make(state: SessionStatus):
        app = create_app()
        app.dependency_overrides[get_current_user] = _current_user
        fake_state = _session_state(state)
        mgr_patcher = patch("app.transport.http.routes.interviews.manager")
        mgr_mock = mgr_patcher.start()
        mgr_mock.get = AsyncMock(return_value=fake_state)
        repo_patcher = patch(
            "app.transport.http.routes.interviews.interview_repo"
        )
        repo_mock = repo_patcher.start()
        repo_mock.get_state_auto = AsyncMock(return_value=fake_state)
        patchers.extend([mgr_patcher, repo_patcher])
        return TestClient(app)

    yield _make

    for p in patchers:
        try:
            p.stop()
        except Exception:
            pass


@pytest.mark.parametrize(
    "status",
    [
        SessionStatus.SUSPENDED,
        SessionStatus.ENDED,
        SessionStatus.CREATED,
        SessionStatus.SETTING_UP,
        SessionStatus.DONE,
        SessionStatus.EXTRACTING,
    ],
)
def test_keyboard_post_rejects_non_in_progress(make_status_client, status):
    """键盘 POST 在非 in_progress 状态 → 409 + WS_SESSION_ENDED。"""
    client = make_status_client(status)
    resp = client.post(
        "/api/v1/interviews/s1/notes/keyboard",
        json={"text": "hi", "client_created_at": "2026-09-23T10:00:00Z"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == Keys.WS_SESSION_ENDED.value


def test_canvas_post_rejects_suspended(make_status_client):
    """画板 POST 在 suspended 状态 → 409 + WS_SESSION_ENDED。"""
    client = make_status_client(SessionStatus.SUSPENDED)
    resp = client.post(
        "/api/v1/interviews/s1/canvases/1",
        json={
            "payload": {"strokes": []},
            "filedata": "aGVsbG8=",
            "client_updated_at": "2026-09-23T10:00:00Z",
        },
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == Keys.WS_SESSION_ENDED.value


def test_canvas_post_rejects_ended(make_status_client):
    """画板 POST 在 ended 状态 → 409。"""
    client = make_status_client(SessionStatus.ENDED)
    resp = client.post(
        "/api/v1/interviews/s1/canvases/1",
        json={
            "payload": {"strokes": []},
            "filedata": "aGVsbG8=",
            "client_updated_at": "2026-09-23T10:00:00Z",
        },
    )
    assert resp.status_code == 409


def test_canvas_delete_allows_ended(make_status_client, monkeypatch):
    """画板 DELETE 不强制状态机,ended 状态也能删。

    mocked delete_canvas_auto 返 image_id=42 → 期望 200 + deleted_ids=[42],
    不被 409 拦。如果返 409,说明状态机被错误地加到 DELETE 路径上。
    """
    client = make_status_client(SessionStatus.ENDED)

    # 让 registry.get 返 None 走 else 分支(走镜像列 mutate_state_auto);
    # mock mutate_state_auto 返 AsyncMock 避免 await MagicMock 报错
    import app.services.sessions.runtime as runtime_mod
    monkeypatch.setattr(runtime_mod.registry, "get", MagicMock(return_value=None))
    monkeypatch.setattr(
        "app.transport.http.routes.interviews.interview_repo.mutate_state_auto",
        AsyncMock(return_value=True),
    )

    # 拦截 service.delete_canvas_auto 返 image_id
    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(
            return_value=SimpleNamespace(id=42)
        )
        sess.execute = AsyncMock(return_value=result_mock)
        sess.delete = AsyncMock()
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.canvas_service as canvas_svc
    monkeypatch.setattr(canvas_svc, "SessionLocal", _ctx)

    resp = client.delete("/api/v1/interviews/s1/canvases/1")
    assert resp.status_code != 409, "DELETE canvas 不应被状态机拦"
    assert resp.status_code == 200
    assert resp.json()["deleted_ids"] == [42]


# ---- runtime=None 时清 DB 镜像列 ----

def test_keyboard_get_allows_paused(make_status_client, monkeypatch):
    """GET /notes/keyboard 暂停状态也能读——报告页要看历史。"""
    from app.services.keyboard.service import get_keyboard_text_auto
    from datetime import datetime, timezone
    from app.domain.note import KeyboardNote

    fake_note = KeyboardNote(
        session_id="s1", user_id="u1", text="已存在的键盘笔记",
        client_created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.services.keyboard.service.get_keyboard_text_auto",
        AsyncMock(return_value=fake_note),
    )

    client = make_status_client(SessionStatus.SUSPENDED)
    resp = client.get("/api/v1/interviews/s1/notes/keyboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["text"] == "已存在的键盘笔记"


def test_keyboard_get_allows_ended(make_status_client, monkeypatch):
    """GET /notes/keyboard ended 状态也能读。"""
    from app.services.keyboard.service import get_keyboard_text_auto
    from datetime import datetime, timezone
    from app.domain.note import KeyboardNote

    fake_note = KeyboardNote(
        session_id="s1", user_id="u1", text="ended 后的笔记",
        client_created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.services.keyboard.service.get_keyboard_text_auto",
        AsyncMock(return_value=fake_note),
    )

    client = make_status_client(SessionStatus.ENDED)
    resp = client.get("/api/v1/interviews/s1/notes/keyboard")
    assert resp.status_code == 200
    assert resp.json()["item"]["text"] == "ended 后的笔记"


def test_canvas_delete_clears_mirror_when_runtime_none(make_status_client, monkeypatch):
    """suspended/ended session 从新标签接入 → DELETE canvas 后 runtime is None 时
    清 DB 镜像列 interviews.handwriting_notes,避免 cold start 加载到已删 image_id 的 OCR。

    旧实现只走 runtime.remove_handwriting_notes 路径,runtime 为 None 时镜像列不动。
    """
    client = make_status_client(SessionStatus.ENDED)

    # delete_canvas_auto 返 image_id=42(模拟真删了行)
    @asynccontextmanager
    async def _canvas_ctx():
        sess = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(
            return_value=SimpleNamespace(id=42),
        )
        sess.execute = AsyncMock(return_value=result_mock)
        sess.delete = AsyncMock()
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.canvas_service as canvas_svc
    monkeypatch.setattr(canvas_svc, "SessionLocal", _canvas_ctx)

    # registry.get 返 None 走 else 分支(mutate_state_auto)
    import app.services.sessions.runtime as runtime_mod
    monkeypatch.setattr(
        runtime_mod.registry, "get", MagicMock(return_value=None),
    )

    # interview_repo.get_state_auto 返含 image_id=42 的 state_mirror
    captured: dict = {}
    from datetime import datetime, timezone
    from app.domain.session_state import HandwritingNoteSegment

    seg_kept = HandwritingNoteSegment(
        image_id=10, text="保留",
        injected_at=datetime.now(timezone.utc),
    )
    seg_deleted = HandwritingNoteSegment(
        image_id=42, text="已删 OCR",
        injected_at=datetime.now(timezone.utc),
    )
    fake_mirror = SimpleNamespace(
        session=SimpleNamespace(id="s1", user_id="u1"),
        keyboard_text=None,
        handwriting_notes=[seg_kept, seg_deleted],
    )

    async def fake_mutate_state_auto(sid, mutator, *, fields=None):
        captured["fields"] = fields
        # 模拟 interview_repo.mutate_state_auto:在锁内 get → 调 mutator →
        # 落盘(mutator 内部对 state 改写,我们要看改写结果)
        state = await fake_get_state_auto(sid)
        mutator(state)
        captured["remaining"] = [
            n.image_id for n in state.handwriting_notes
        ]
        return True

    async def fake_get_state_auto(sid):
        return fake_mirror

    # fixture 把 interview_repo 整个换成了 MagicMock,跨模块引用 id 不同——
    # 必须 patch handler 实际 import 的那个引用,持久层改的 patch 是死路径。
    monkeypatch.setattr(
        "app.transport.http.routes.interviews.interview_repo.mutate_state_auto",
        fake_mutate_state_auto,
    )
    monkeypatch.setattr(
        "app.transport.http.routes.interviews.interview_repo.get_state_auto",
        fake_get_state_auto,
    )

    resp = client.delete("/api/v1/interviews/s1/canvases/1")
    assert resp.status_code == 200
    assert resp.json()["deleted_ids"] == [42]
    # 镜像列必须按 notes 分组写回,且已删 image_id 已被过滤
    assert captured["fields"] == {"notes"}
    assert captured["remaining"] == [10]  # image_id=42 的段被过滤掉
