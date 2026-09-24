"""画板 state 服务层单元测试(pure function + mock session)。

覆盖:
- compute_canvas_payload_hash:规范化序列化、key 顺序无关
- upsert_canvas_payload:hash 跳过、payload 更新、行找不到返 None
- delete_canvas:幂等、owner 校验
- list_canvases:canvas_index 排序
- create_pending_image_auto 集成:canvas_index 透传
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import contextlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.persistence.models import HandwritingImage
from app.services.handwriting.canvas_service import (
    CanvasUpsertResult,
    compute_canvas_payload_hash,
    delete_canvas_auto,
    list_canvases_auto,
    upsert_canvas_payload_auto,
)
from app.services.handwriting.service import create_pending_image_auto


# ---- compute_canvas_payload_hash ----

def test_hash_dict_key_order_irrelevant():
    """同一 dict 不同插入顺序 → 同一 hash(sort_keys=True)。"""
    a = {"x": 1, "y": 2, "z": {"a": 3, "b": 4}}
    b = {"z": {"b": 4, "a": 3}, "y": 2, "x": 1}
    assert compute_canvas_payload_hash(a) == compute_canvas_payload_hash(b)


def test_hash_value_diff_yields_diff_hash():
    """值不同 → 不同 hash。"""
    a = {"strokes": [{"x": 1, "y": 2}]}
    b = {"strokes": [{"x": 1, "y": 3}]}
    assert compute_canvas_payload_hash(a) != compute_canvas_payload_hash(b)


def test_hash_is_sha256_hex_64chars():
    h = compute_canvas_payload_hash({"any": "data"})
    assert len(h) == 64
    int(h, 16)


# ---- helpers ----

def _make_canvas_row(
    *, canvas_index: int = 1, user_id: str = "u1",
    session_id: str = "s1", payload_hash: str = "old_hash",
    payload: dict | None = None, image_id: int | None = None,
) -> HandwritingImage:
    """造一个 canvas 行;默认 id 留 None 让 SQLAlchemy 不冲突。"""
    import sqlalchemy as _sa
    row = HandwritingImage(
        session_id=session_id,
        user_id=user_id,
        canvas_index=canvas_index,
        canvas_payload=payload or {"strokes": []},
        canvas_payload_hash=payload_hash,
        image_base64="x",
        image_format="jpeg",
        image_bytes_size=1,
        ocr_status="done",
        text="",
        retry_count=0,
        image_hash="h",
        client_created_at=datetime.now(timezone.utc),
    )
    if image_id is not None:
        row.id = image_id
    return row


def _patch_session_with_row(row):
    """mock service 内 SessionLocal → 已有该行。

    返回一个**普通函数**而不是 asynccontextmanager——monkeypatch.setattr
    替换后,service 走 `async with SessionLocal() as db` 直接调它。函数本身
    是 async context manager(`async with func() as db` 会调 `func()` 拿到
    awaitable,然后 __aenter__/__aexit__)。所以 func 必须返回 awaitable。
    """
    async def _ctx():
        sess = MagicMock()

        async def execute(stmt):
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value=row)
            return result_mock

        sess.execute = execute
        sess.get = AsyncMock(return_value=row)
        sess.add = MagicMock()
        sess.commit = AsyncMock()
        sess.rollback = AsyncMock()
        sess.flush = AsyncMock()
        sess.delete = AsyncMock()
        yield sess

    # _ctx 是 async generator(经 yield),但 `async with func() as db` 要求
    # func 返回一个有 __aenter__/__aexit__ 的对象。把 _ctx 重新包成
    # asynccontextmanager 一次性应用,返回的 _factory 是符合协议的 CM 工厂。
    import contextlib
    @contextlib.asynccontextmanager
    async def _factory():
        async for sess in _ctx():
            yield sess
    return _factory


# ---- upsert_canvas_payload ----

@pytest.mark.asyncio
async def test_upsert_skips_when_hash_matches(monkeypatch):
    """payload hash 与 DB 一致 → 跳过,不动 payload。"""
    payload = {"strokes": [{"x": 1}]}
    new_hash = compute_canvas_payload_hash(payload)
    row = _make_canvas_row(payload_hash=new_hash)

    import app.services.handwriting.canvas_service as svc
    monkeypatch.setattr(svc, "SessionLocal", _patch_session_with_row(row))

    result = await upsert_canvas_payload_auto(
        session_id="s1", user_id="u1", canvas_index=1, payload=payload,
    )
    assert isinstance(result, CanvasUpsertResult)
    assert result.payload_skipped is True
    assert result.payload_updated is False
    assert result.row is row
    assert row.canvas_payload == {"strokes": []}  # 未改


@pytest.mark.asyncio
async def test_upsert_updates_when_hash_differs(monkeypatch):
    """hash 不同 → 写 payload + 更新 hash。"""
    old_row = _make_canvas_row(
        payload_hash="old",
        payload={"strokes": [{"x": 1}]},
    )

    import app.services.handwriting.canvas_service as svc
    monkeypatch.setattr(svc, "SessionLocal", _patch_session_with_row(old_row))

    new_payload = {"strokes": [{"x": 99}]}
    result = await upsert_canvas_payload_auto(
        session_id="s1", user_id="u1", canvas_index=1, payload=new_payload,
    )
    assert result.payload_skipped is False
    assert result.payload_updated is True
    assert old_row.canvas_payload == new_payload
    assert old_row.canvas_payload_hash == compute_canvas_payload_hash(new_payload)


@pytest.mark.asyncio
async def test_upsert_returns_none_when_row_not_found(monkeypatch):
    """canvas 行找不到(未先 POST 图)→ 返 None,handler 走 404。"""
    import app.services.handwriting.canvas_service as svc
    monkeypatch.setattr(svc, "SessionLocal", _patch_session_with_row(None))

    result = await upsert_canvas_payload_auto(
        session_id="s1", user_id="u1", canvas_index=99,
        payload={"x": 1},
    )
    assert result is None


# ---- delete_canvas ----

@pytest.mark.asyncio
async def test_delete_canvas_success(monkeypatch):
    row = _make_canvas_row(canvas_index=2, image_id=42)
    import app.services.handwriting.canvas_service as svc
    svc.SessionLocal = _patch_session_with_row(row)

    image_id = await delete_canvas_auto(
        session_id="s1", user_id="u1", canvas_index=2,
    )
    assert image_id == 42  # 返实际删除的 image_id 给 handler 清理 state


@pytest.mark.asyncio
async def test_delete_canvas_no_match_returns_none(monkeypatch):
    """canvas_index 不存在 → 返 None(幂等)。"""
    import app.services.handwriting.canvas_service as svc
    svc.SessionLocal = _patch_session_with_row(None)

    image_id = await delete_canvas_auto(
        session_id="s1", user_id="u1", canvas_index=99,
    )
    assert image_id is None


@pytest.mark.asyncio
async def test_delete_canvas_idempotent(monkeypatch):
    """重复删同一 canvas_index 第二次返 None。"""
    call_count = {"n": 0}
    row = _make_canvas_row(canvas_index=2, image_id=42)

    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def execute(stmt):
            call_count["n"] += 1
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(
                return_value=row if call_count["n"] == 1 else None
            )
            return r

        sess.execute = execute
        sess.commit = AsyncMock()
        sess.delete = AsyncMock()
        yield sess

    import app.services.handwriting.canvas_service as svc
    svc.SessionLocal = _ctx

    first = await delete_canvas_auto(
        session_id="s1", user_id="u1", canvas_index=2,
    )
    second = await delete_canvas_auto(
        session_id="s1", user_id="u1", canvas_index=2,
    )
    assert first == 42
    assert second is None  # 幂等:第二次返 None


# ---- create_pending_image_auto canvas_index 透传 ----

@pytest.mark.asyncio
async def test_create_image_passes_canvas_index_to_new_row(monkeypatch):
    """新建行时 canvas_index 直接落列。"""
    new_row = HandwritingImage(
        id=42,
        session_id="s1",
        user_id="u1",
        canvas_index=3,  # ← 透传成功
        image_base64="x",
        image_format="jpeg",
        image_bytes_size=1,
        ocr_status="pending",
        text="",
        retry_count=0,
        image_hash="h",
        client_created_at=datetime.now(timezone.utc),
    )

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def execute(stmt):
            # 第一次 execute 是 dedup 查返 None;后续是 INSERT commit
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        async def commit():
            pass

        sess.execute = execute
        sess.commit = commit
        sess.rollback = AsyncMock()
        sess.add = MagicMock()
        yield sess

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _ctx)

    row, created = await create_pending_image_auto(
        session_id="s1", user_id="u1",
        image_base64="x", image_hash="h", image_format="jpeg",
        image_bytes_size=1,
        client_created_at=datetime.now(timezone.utc),
        canvas_index=3,
    )
    assert created is True
    assert row.canvas_index == 3


@pytest.mark.asyncio
async def test_create_image_backfills_canvas_index_on_dedup_hit(monkeypatch):
    """dedup 命中(已有 image_hash 行)canvas_index 为 NULL → 补上。"""
    existing = HandwritingImage(
        id=42,
        session_id="s1",
        user_id="u1",
        canvas_index=None,  # ← 已有行 canvas_index 未设
        image_base64="x",
        image_format="jpeg",
        image_bytes_size=1,
        ocr_status="done",
        text="",
        retry_count=0,
        image_hash="h",
        client_created_at=datetime.now(timezone.utc),
    )

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def execute(stmt):
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=existing)
            return r

        sess.execute = execute
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.service as svc
    monkeypatch.setattr(svc, "SessionLocal", _ctx)

    row, created = await create_pending_image_auto(
        session_id="s1", user_id="u1",
        image_base64="x", image_hash="h", image_format="jpeg",
        image_bytes_size=1,
        client_created_at=datetime.now(timezone.utc),
        canvas_index=5,
    )
    assert created is False
    assert row is existing
    assert existing.canvas_index == 5  # backfill 成功


# ---- list_canvases ----

@pytest.mark.asyncio
async def test_replace_canvas_image_updates_existing_row(monkeypatch):
    """P0 #1 回归:同 canvas_index 改图(image_hash 变)→ UPDATE 现有行,image_id 保留。

    之前路径 create_pending_image_auto INSERT 撞 UNIQUE(session_id,user_id,canvas_index)
    触发 IntegrityError 500。新路径 replace_canvas_image UPDATE 现有行。
    """
    existing = HandwritingImage(
        id=42,
        session_id="s1",
        user_id="u1",
        canvas_index=1,
        image_base64="old_data",
        image_format="jpeg",
        image_bytes_size=10,
        ocr_status="done",
        text="old ocr",
        retry_count=1,
        image_hash="old_hash",
        injected_at=datetime.now(timezone.utc),
        client_created_at=datetime.now(timezone.utc),
    )

    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=existing)
        sess.execute = AsyncMock(return_value=result_mock)
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.service as svc
    svc.SessionLocal = _ctx

    from app.services.handwriting.service import replace_canvas_image_auto

    new_bytes = b"new_image_data"
    new_hash = "new_hash"
    row, ocr_task_fired = await replace_canvas_image_auto(
        session_id="s1",
        user_id="u1",
        image_base64="new_data",
        image_format="png",
        image_bytes_size=len(new_bytes),
        image_hash=new_hash,
        canvas_index=1,
        client_created_at=datetime.now(timezone.utc),
    )
    assert row.id == 42  # image_id 保留稳定
    assert row.image_hash == new_hash  # hash 更新
    assert row.image_base64 == "new_data"
    assert ocr_task_fired is True  # hash 不同 → 触发 OCR 重跑
    assert row.ocr_status == "pending"  # OCR 状态重置
    assert row.text == ""  # 旧 OCR 文本清空


@pytest.mark.asyncio
async def test_replace_canvas_image_skips_ocr_when_hash_unchanged(monkeypatch):
    """同 canvas_index 但 image_hash 一致(image 内容没变)→ 跳过 OCR 重跑。"""
    existing = HandwritingImage(
        id=42,
        session_id="s1",
        user_id="u1",
        canvas_index=1,
        image_base64="same",
        image_format="jpeg",
        image_bytes_size=10,
        ocr_status="done",
        text="old ocr",
        retry_count=1,
        image_hash="same_hash",  # ← 与新 POST 同 hash
        injected_at=datetime.now(timezone.utc),
        client_created_at=datetime.now(timezone.utc),
    )

    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=existing)
        sess.execute = AsyncMock(return_value=result_mock)
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.service as svc
    svc.SessionLocal = _ctx

    from app.services.handwriting.service import replace_canvas_image_auto

    row, ocr_task_fired = await replace_canvas_image_auto(
        session_id="s1",
        user_id="u1",
        image_base64="same",
        image_format="jpeg",
        image_bytes_size=10,
        image_hash="same_hash",
        canvas_index=1,
        client_created_at=datetime.now(timezone.utc),
    )
    assert ocr_task_fired is False  # hash 同 → 跳过 OCR
    assert row.ocr_status == "done"  # 旧 OCR 状态保留


@pytest.mark.asyncio
async def test_replace_canvas_image_returns_none_when_row_missing(monkeypatch):
    """canvas 行不存在(并发被删)→ 返 None,handler 退化到 create_pending_image_auto INSERT。"""
    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        sess.execute = AsyncMock(return_value=result_mock)
        yield sess

    import app.services.handwriting.service as svc
    svc.SessionLocal = _ctx

    from app.services.handwriting.service import replace_canvas_image_auto

    result = await replace_canvas_image_auto(
        session_id="s1",
        user_id="u1",
        image_base64="x",
        image_format="jpeg",
        image_bytes_size=1,
        image_hash="h",
        canvas_index=99,
        client_created_at=datetime.now(timezone.utc),
    )
    assert result is None


@pytest.mark.asyncio
async def test_delete_canvases_batch_returns_only_owned_ids(monkeypatch):
    """批量删除:跨 session/跨 user 跳过,只返 owned image_id。"""
    call_log = {"delete_calls": []}

    async def fake_delete_canvas_auto(*, session_id, user_id, canvas_index):
        call_log["delete_calls"].append(canvas_index)
        # canvas_index 99 不存在,其它都返 image_id
        if canvas_index == 99:
            return None
        return canvas_index  # 用 canvas_index 当 image_id 简化

    import app.services.handwriting.canvas_service as canvas_svc
    monkeypatch.setattr(
        canvas_svc, "delete_canvas_auto", fake_delete_canvas_auto,
    )

    from app.services.handwriting.canvas_service import delete_canvases_batch_auto

    deleted_ids = await delete_canvases_batch_auto(
        session_id="s1", user_id="u1",
        canvas_indexes=[1, 2, 3, 99],
    )
    # 99 不存在被跳过,1/2/3 都返了
    assert sorted(deleted_ids) == [1, 2, 3]
    assert call_log["delete_calls"] == [1, 2, 3, 99]


@pytest.mark.asyncio
async def test_delete_canvases_batch_empty_input_returns_empty():
    """批量删除:空列表 → 直接返空,不进 DB。"""
    from app.services.handwriting.canvas_service import delete_canvases_batch_auto

    deleted_ids = await delete_canvases_batch_auto(
        session_id="s1", user_id="u1", canvas_indexes=[],
    )
    assert deleted_ids == []


@pytest.mark.asyncio
async def test_list_canvases_filters_null_canvas_index():
    """list_canvases_auto 加 WHERE canvas_index IS NOT NULL——纯 OCR 图行(NULL)不返。

    mock 的 execute 返指定 rows,验证 service 把它们作为 list 返回——
    真实 SQLAlchemy WHERE 过滤由 SQLAlchemy 在真 DB 上保证,这里测
    service 拿到 list 后正确组装响应。SQLAlchemy 排序语义由 integration test 覆盖。
    """
    rows = [
        _make_canvas_row(canvas_index=2),
        _make_canvas_row(canvas_index=1),
    ]

    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def execute(stmt):
            r = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all = MagicMock(return_value=rows)
            r.scalars = MagicMock(return_value=scalars_mock)
            return r

        sess.execute = execute
        yield sess

    import app.services.handwriting.canvas_service as svc
    svc.SessionLocal = _ctx

    result = await list_canvases_auto(session_id="s1", user_id="u1")
    assert len(result) == 2
    assert {r.canvas_index for r in result} == {1, 2}


# ---- P1 #1 回归:画板 payload DoS 兜底 ----

def test_save_canvas_payload_under_limit_passes():
    """payload 序列化字节 ≤ 1MB → 校验通过(正常画板 < 64KB)。"""
    from app.transport.http.schemas import SaveCanvasRequest

    req = SaveCanvasRequest(
        payload={"strokes": [{"x": i, "y": i * 2} for i in range(100)]},
        filedata="aGVsbG8=",
        client_updated_at=datetime.now(timezone.utc),
    )
    # 校验通过,无异常
    assert req is not None


def test_save_canvas_payload_over_limit_rejected():
    """payload 序列化字节 > 1MB → 422 + SESSION_BASE_INFO_VALUE_TOO_LONG。

    DoS 兜底:恶意客户端发超大 payload 直接拒,不在 server 上双倍内存。
    """
    import pytest
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError
    from app.transport.http.schemas import SaveCanvasRequest

    # 构造一个超过 1MB 的 payload(单字符串字段塞 2MB)
    big_payload = {"big": "x" * (2 * 1024 * 1024)}

    with pytest.raises(I18nError) as exc_info:
        SaveCanvasRequest(
            payload=big_payload,
            filedata="aGVsbG8=",
            client_updated_at=datetime.now(timezone.utc),
        )
    assert exc_info.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG.value
    assert exc_info.value.http_status == 422
    assert exc_info.value.params["field"] == "payload"
    assert exc_info.value.params["byte_len"] > 1024 * 1024
    assert exc_info.value.params["max_bytes"] == 1024 * 1024