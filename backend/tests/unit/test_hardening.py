"""安全/资源加固回归：CORS 只注册一次、JWT issuer 校验、save 锁回收、挂起通知语义。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest

from app.core.exceptions import AuthError
from app.core.i18n import Keys, t
from app.services.auth.token import _AUDIENCE, _ISSUER, _SIGNING_ALG, decode_token
from app.services.sessions.runtime import SessionRuntime
from app.transport.base import extract_auth


# ---- CORS：只允许注册一次（重复注册 = 死代码，且会叠出双份预检头） ----


def test_cors_middleware_registered_once():
    from fastapi.middleware.cors import CORSMiddleware

    from app.app import create_app

    app = create_app()
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1, f"CORSMiddleware 注册了 {len(cors)} 次"


# ---- JWT：decode 必须校验 issuer（防止同密钥签发的其它系统 token 混入） ----
# jwt_secret 由 lifespan 从 DB 注入，单测里为 None → patch 掉 settings


@pytest.fixture
def fake_jwt_secret(monkeypatch):
    import app.services.auth.token as token_mod

    monkeypatch.setattr(token_mod, "get_settings",
                        lambda: SimpleNamespace(jwt_secret="test-secret"))


def _make_token(iss: str = _ISSUER) -> str:
    return pyjwt.encode(
        {"sub": "u1", "iss": iss, "aud": _AUDIENCE},
        "test-secret", algorithm=_SIGNING_ALG,
    )


def test_decode_accepts_own_token(fake_jwt_secret):
    payload = decode_token(_make_token())
    assert payload["sub"] == "u1"
    assert payload["iss"] == _ISSUER


def test_decode_rejects_wrong_issuer(fake_jwt_secret):
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(_make_token(iss="other-system"))


def test_extract_auth_rejects_wrong_issuer_token(fake_jwt_secret):
    with pytest.raises(AuthError):
        extract_auth("Bearer " + _make_token(iss="other-system"))


# ---- save 锁：用完回收，字典不随历史会话数无限增长 ----


async def test_save_lock_kept_while_contended():
    """有任务排队等锁时不回收——删了会让后来者 setdefault 新锁与等待者并行。"""
    from app.persistence.repositories.interview import InterviewRepository

    repo = InterviewRepository()
    lock = repo._save_lock("s1")
    await lock.acquire()

    waiter = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)  # 让 waiter 进入等待队列
    assert lock._waiters, "前置失败：waiter 未入队"

    repo._release_save_lock("s1", lock)  # 有等待者：应跳过回收
    assert repo._save_locks.get("s1") is lock

    lock.release()
    await waiter
    repo._release_save_lock("s1", lock)  # 无人排队：回收
    assert "s1" not in repo._save_locks


async def test_save_lock_recycled_via_save_state():
    """端到端一点：save_state 走完后锁不残留在字典里。"""
    from app.persistence.db import SessionLocal
    from app.persistence.repositories.interview import InterviewRepository
    from app.persistence.repositories.interview import InterviewRecord

    sid = "s-lock-recycle-test"
    state = SimpleNamespace(
        session=SimpleNamespace(
            id=sid, status=SimpleNamespace(value="created"),
            template_id="pm-research", template_version="1", user_id="u1",
            base_info={}, goal="g", first_batch_generated=False, consumed_seq=0,
            created_at=None, started_at=None, ended_at=None,
        ),
        transcript=[], items=[], skipped_ids=set(), ignored_ids=set(), coverage={},
    )

    repo = InterviewRepository()
    async with SessionLocal() as db:
        await repo.save_state(db, state)
        assert sid not in repo._save_locks, "save_state 完成后锁应被回收"
        rec = await db.get(InterviewRecord, sid)
        if rec is not None:  # 清理测试落库的行
            await db.delete(rec)
            await db.commit()


async def test_save_state_cannot_regress_from_ended():
    """ended 终态粘性：寄存 runtime 的旧快照（suspended/in_progress）落盘时，
    不得把 DB 里已 ended 的会话写回进行中——REST end 后台拆除与 manager
    各持不同 SessionState 对象，旧快照全量回写会把已结束的访谈「复活」。"""
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.persistence.db import SessionLocal
    from app.persistence.repositories.interview import InterviewRepository, InterviewRecord

    sid = f"s-ended-{uuid4().hex[:12]}"
    ended_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created_at = datetime(2025, 12, 30, tzinfo=timezone.utc)

    def _state(status: str):
        return SimpleNamespace(
            session=SimpleNamespace(
                id=sid, status=SimpleNamespace(value=status),
                template_id="pm-research", template_version="1", user_id="u1",
                base_info={}, goal="g", first_batch_generated=False, consumed_seq=0,
                created_at=created_at, started_at=None,
                ended_at=ended_at if status == "ended" else None,
            ),
            transcript=[], items=[], skipped_ids=set(), ignored_ids=set(), coverage={},
        )

    repo = InterviewRepository()
    async with SessionLocal() as db:
        try:
            await repo.save_state(db, _state("ended"))
            # 旧快照回写：status=suspended、ended_at=None
            await repo.save_state(db, _state("suspended"))
            rec = await db.get(InterviewRecord, sid)
            assert rec.status == "ended", f"ended 被旧快照回写为 {rec.status}"
            assert rec.ended_at.replace(tzinfo=None) == ended_at.replace(tzinfo=None), \
                "ended_at 被旧快照清空"
        finally:
            rec = await db.get(InterviewRecord, sid)
            if rec is not None:
                await db.delete(rec)
                await db.commit()


# ---- idle 挂起：通知语义是 suspended（4403），不是 ended（4406） ----


def _runtime(make_state):
    rt = SessionRuntime(make_state())
    rt.engine = MagicMock()
    rt.engine.on_end = AsyncMock()
    rt.pipeline = MagicMock()
    rt.pipeline.flush = AsyncMock()
    rt.pipeline.close = AsyncMock()
    rt._force_flush = AsyncMock()
    return rt


async def test_suspend_notifies_suspended_and_closes_4403(make_state):
    """suspend：发 session.suspended + 4403，不做辅导终局重算。"""
    rt = _runtime(make_state)
    sent, evicted = [], []
    rt._send_fn = AsyncMock(side_effect=lambda m: sent.append(m))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.suspend()
    assert any(m.get("type") == "session.suspended" for m in sent)
    assert not any(m.get("type") == "session.ended" for m in sent)
    # 用 i18n 目录里的 WS_CLOSE_SUSPENDED 字串对照，不硬编码中文——避免 i18n 文案微调
    # 导致断言变脆。state.locale=None 时回退到 DEFAULT (zh-CN)。
    assert evicted == [(4403, t(Keys.WS_CLOSE_SUSPENDED.value, locale=rt.state.locale))]
    rt.engine.on_end.assert_not_awaited()  # 会话可继续，无终局重算
    assert rt._fsm.is_terminated


async def test_end_still_notifies_ended_4406(make_state):
    """end 语义不变：session.ended + 4406 + 终局重算。"""
    rt = _runtime(make_state)
    sent, evicted = [], []
    rt._send_fn = AsyncMock(side_effect=lambda m: sent.append(m))
    rt._evict_fn = AsyncMock(side_effect=lambda c, r: evicted.append((c, r)))
    await rt.end()
    assert any(m.get("type") == "session.ended" for m in sent)
    # 同上：用 i18n 目录字串对照，绕开硬编码中文的脆性。
    assert evicted == [(4406, t(Keys.WS_CLOSE_SESSION_ENDED.value, locale=rt.state.locale))]
    rt.engine.on_end.assert_awaited_once()
