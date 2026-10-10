"""笔记服务层(键盘 UPSERT / 手写 dedup / 删除归属校验)单测。

不依赖真实 DB——用 MagicMock 模拟 SessionLocal 上下文,捕获"哪些行被改"的副作用。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.persistence.models import HandwritingImage, SessionKeyboardText


def _owned_image(
    *, image_id: int, session_id: str, user_id: str, hash_value: str,
) -> HandwritingImage:
    return HandwritingImage(
        id=image_id,
        session_id=session_id,
        user_id=user_id,
        image_base64="x",
        image_format="jpeg",
        image_bytes_size=1,
        ocr_status="done",
        text="",
        retry_count=0,
        image_hash=hash_value,
        client_created_at=datetime.now(timezone.utc),
    )


def _make_session_factory(sess_mock):
    """生成一个可作 SessionLocal 替换的 async ctx manager。"""
    @asynccontextmanager
    async def _ctx():
        yield sess_mock
    return _ctx


# ---- 键盘 UPSERT ----

@pytest.mark.asyncio
async def test_keyboard_upsert_first_call_creates_row(monkeypatch):
    """首次调用(SQLite 路径):行不存在 → add 新行。

    service 从 db.bind.dialect.name 拿方言,sqlite 走 select-then-add 路径。
    """
    from app.services.keyboard.service import upsert_keyboard_text

    added: list = []
    sess_mock = MagicMock()
    sess_mock.bind = MagicMock(dialect=MagicMock(name="sqlite"))
    sess_mock.get = AsyncMock(return_value=None)

    def _add(obj):
        added.append(obj)

    sess_mock.add = _add
    sess_mock.commit = AsyncMock()
    sess_mock.rollback = AsyncMock()
    sess_mock.flush = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield sess_mock

    import app.services.keyboard.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _ctx)

    async with svc.SessionLocal() as db:
        await upsert_keyboard_text(
            db,
            session_id="s1",
            user_id="u1",
            text="hello",
            client_created_at=datetime.now(timezone.utc),
        )
        await db.commit()

    assert len(added) == 1
    row = added[0]
    assert isinstance(row, SessionKeyboardText)
    assert row.text == "hello"


@pytest.mark.asyncio
async def test_keyboard_upsert_overwrites_existing_text(monkeypatch):
    """第二次调用(SQLite 路径):已存在行 → 改 text,不新增,client_created_at 保留。"""
    from app.services.keyboard.service import upsert_keyboard_text

    initial_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = SessionKeyboardText(
        session_id="s1",
        user_id="u1",
        text="v1",
        client_created_at=initial_created_at,
    )
    by_pk = {("s1", "u1"): row}

    sess_mock = MagicMock()
    sess_mock.bind = MagicMock(dialect=MagicMock(name="sqlite"))

    async def get(cls, pk):
        return by_pk.get(pk)

    sess_mock.get = get
    sess_mock.add = MagicMock()
    sess_mock.commit = AsyncMock()
    sess_mock.rollback = AsyncMock()
    sess_mock.flush = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield sess_mock

    import app.services.keyboard.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _ctx)

    new_created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    async with svc.SessionLocal() as db:
        await upsert_keyboard_text(
            db,
            session_id="s1",
            user_id="u1",
            text="v2",
            client_created_at=new_created_at,
        )

    assert sess_mock.add.call_count == 0  # 无新增
    assert row.text == "v2"  # 现有行被改 text
    assert row.client_created_at == initial_created_at  # 原值保留


# ---- 手写删除 ----

@pytest.mark.asyncio
async def test_handwriting_delete_skips_cross_user(monkeypatch):
    """DELETE 跨用户:跳过——A 的图不会被 B 删。"""
    from app.services.handwriting.service import delete_handwriting_image_auto

    a_image = _owned_image(
        image_id=10, session_id="s1", user_id="user-A", hash_value="h",
    )
    sess_mock = MagicMock()
    sess_mock.get = AsyncMock(return_value=a_image)
    sess_mock.delete = MagicMock()
    sess_mock.commit = AsyncMock()

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _make_session_factory(sess_mock))

    deleted = await delete_handwriting_image_auto(
        session_id="s1",
        user_id="user-B",  # 跨用户
        image_id=10,
    )
    assert deleted is False
    assert sess_mock.delete.call_count == 0


@pytest.mark.asyncio
async def test_handwriting_delete_skips_cross_session(monkeypatch):
    """DELETE 跨 session:跳过。"""
    from app.services.handwriting.service import delete_handwriting_image_auto

    img = _owned_image(
        image_id=10, session_id="session-A", user_id="u1", hash_value="h",
    )
    sess_mock = MagicMock()
    sess_mock.get = AsyncMock(return_value=img)
    sess_mock.delete = MagicMock()
    sess_mock.commit = AsyncMock()

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _make_session_factory(sess_mock))

    deleted = await delete_handwriting_image_auto(
        session_id="session-B",
        user_id="u1",
        image_id=10,
    )
    assert deleted is False
    assert sess_mock.delete.call_count == 0


@pytest.mark.asyncio
async def test_handwriting_delete_owner_match_succeeds(monkeypatch):
    """DELETE 三匹配 → 实际删(返 True)。"""
    from app.services.handwriting.service import delete_handwriting_image_auto

    img = _owned_image(
        image_id=10, session_id="s1", user_id="u1", hash_value="h",
    )
    sess_mock = MagicMock()
    sess_mock.get = AsyncMock(return_value=img)
    sess_mock.delete = AsyncMock()
    sess_mock.commit = AsyncMock()

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _make_session_factory(sess_mock))

    deleted = await delete_handwriting_image_auto(
        session_id="s1",
        user_id="u1",
        image_id=10,
    )
    assert deleted is True
    assert sess_mock.delete.call_count == 1


@pytest.mark.asyncio
async def test_handwriting_delete_idempotent(monkeypatch):
    """重复删同一 image_id 第二次 → 返 False(handler 仍 200,空 deleted_ids)。"""
    from app.services.handwriting.service import delete_handwriting_image_auto

    # 第一次 get 命中,第二次 get 返 None(已删)
    call_count = {"n": 0}
    img = _owned_image(
        image_id=10, session_id="s1", user_id="u1", hash_value="h",
    )

    sess_mock = MagicMock()

    async def get(cls, pk):
        call_count["n"] += 1
        return img if call_count["n"] == 1 else None

    sess_mock.get = get
    sess_mock.delete = AsyncMock()
    sess_mock.commit = AsyncMock()

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _make_session_factory(sess_mock))

    first = await delete_handwriting_image_auto(
        session_id="s1", user_id="u1", image_id=10,
    )
    second = await delete_handwriting_image_auto(
        session_id="s1", user_id="u1", image_id=10,
    )
    assert first is True
    assert second is False  # 幂等:第二次无副作用


@pytest.mark.asyncio
async def test_handwriting_batch_delete_empty_returns_empty(monkeypatch):
    """batch_delete:空 image_ids → 返空,不进 SessionLocal。"""
    from app.services.handwriting.service import delete_handwriting_images_batch_auto

    opened = {"yes": False}

    @asynccontextmanager
    async def _ctx():
        opened["yes"] = True
        yield MagicMock()

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _ctx)

    deleted_ids = await delete_handwriting_images_batch_auto(
        session_id="s1",
        user_id="u1",
        image_ids=[],
    )
    assert deleted_ids == []
    assert opened["yes"] is False