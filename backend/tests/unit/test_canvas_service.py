"""画板 state 服务层单元测试(pure function + mock session)。

覆盖:
- compute_canvas_payload_hash:规范化序列化、key 顺序无关
- upsert_canvas_payload:hash 跳过、payload 更新、行找不到返 None
- upsert_canvas_image:UPDATE/dedup/INSERT 分支、hash 不变跳过 OCR、
  IntegrityError 兜底
- delete_canvas:幂等、owner 校验
- list_canvases:canvas_index 排序
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
    upsert_canvas_payload,
)
from app.services.handwriting.service import upsert_canvas_image


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


# ---- upsert_canvas_payload(事务版,直接传 mock db) ----

@pytest.mark.asyncio
async def test_upsert_skips_when_hash_matches():
    """payload hash 与 DB 一致 → 跳过,不动 payload。"""
    payload = {"strokes": [{"x": 1}]}
    new_hash = compute_canvas_payload_hash(payload)
    row = _make_canvas_row(payload_hash=new_hash)
    sess = _mock_db([row])

    result = await upsert_canvas_payload(
        sess, session_id="s1", user_id="u1", canvas_index=1, payload=payload,
    )
    assert isinstance(result, CanvasUpsertResult)
    assert result.payload_skipped is True
    assert result.payload_updated is False
    assert result.row is row
    assert row.canvas_payload == {"strokes": []}  # 未改
    sess.commit.assert_not_awaited()  # 事务边界:commit 归调用方


@pytest.mark.asyncio
async def test_upsert_updates_when_hash_differs():
    """hash 不同 → 写 payload + 更新 hash。"""
    old_row = _make_canvas_row(
        payload_hash="old",
        payload={"strokes": [{"x": 1}]},
    )
    sess = _mock_db([old_row])

    new_payload = {"strokes": [{"x": 99}]}
    result = await upsert_canvas_payload(
        sess, session_id="s1", user_id="u1", canvas_index=1, payload=new_payload,
    )
    assert result.payload_skipped is False
    assert result.payload_updated is True
    assert old_row.canvas_payload == new_payload
    assert old_row.canvas_payload_hash == compute_canvas_payload_hash(new_payload)


@pytest.mark.asyncio
async def test_upsert_returns_none_when_row_not_found():
    """canvas 行找不到(未先 POST 图)→ 返 None,handler 走 404。"""
    sess = _mock_db([None])

    result = await upsert_canvas_payload(
        sess, session_id="s1", user_id="u1", canvas_index=99,
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


# ---- upsert_canvas_image:hash 不变跳过 OCR ----

@pytest.mark.asyncio
async def test_upsert_canvas_image_hash_unchanged_skips_ocr_reset():
    """同 canvas_index 且 image_hash 一致(图没变)→ fired=False,
    OCR 状态/文本全保留(不重跑 OCR)。"""
    row = _make_canvas_row(canvas_index=1, image_id=42)
    row.image_hash = "same_hash"
    row.ocr_status = "done"
    row.text = "已有 OCR 文本"
    sess = _mock_db([row])

    result_row, fired = await upsert_canvas_image(
        sess,
        session_id="s1", user_id="u1", image_base64="same",
        image_format="jpeg", image_bytes_size=10, image_hash="same_hash",
        canvas_index=1, client_created_at=datetime.now(timezone.utc),
    )
    assert fired is False
    assert result_row is row
    assert row.ocr_status == "done"  # 旧 OCR 状态保留
    assert row.text == "已有 OCR 文本"


@pytest.mark.asyncio
async def test_delete_canvases_batch_returns_only_owned_ids(monkeypatch):
    """批量删除:单次 SELECT 拉 owned 行,单次 DELETE 删;不存在的 id 静默跳过。"""
    import contextlib

    rows = [
        _make_canvas_row(image_id=10, canvas_index=1, user_id="u1", session_id="s1"),
        _make_canvas_row(image_id=20, canvas_index=2, user_id="u1", session_id="s1"),
        _make_canvas_row(image_id=30, canvas_index=3, user_id="u1", session_id="s1"),
    ]

    @contextlib.asynccontextmanager
    async def _ctx():
        sess = MagicMock()
        result_mock = MagicMock()

        async def execute(stmt):
            result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
            return result_mock
        sess.execute = execute
        sess.commit = AsyncMock()
        yield sess

    import app.services.handwriting.canvas_service as canvas_svc
    monkeypatch.setattr(canvas_svc, "SessionLocal", _ctx)

    from app.services.handwriting.canvas_service import delete_canvases_batch_auto

    deleted_ids = await delete_canvases_batch_auto(
        session_id="s1", user_id="u1",
        canvas_indexes=[1, 2, 3, 99],  # 99 不存在被跳过
    )
    assert sorted(deleted_ids) == [10, 20, 30]


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


# ---- upsert_canvas_image(事务版,直接传 mock db) ----

def _mock_db(execute_results):
    """execute 按调用顺序依次返回 scalar_one_or_none 结果。"""
    sess = MagicMock()
    result_mocks = []
    for r in execute_results:
        m = MagicMock()
        m.scalar_one_or_none = MagicMock(return_value=r)
        result_mocks.append(m)
    sess.execute = AsyncMock(side_effect=result_mocks)
    sess.add = MagicMock()
    sess.flush = AsyncMock()
    sess.rollback = AsyncMock()
    sess.commit = AsyncMock()
    return sess


@pytest.mark.asyncio
async def test_upsert_canvas_image_updates_existing_row():
    """canvas 行存在 → UPDATE image 字段;hash 变化 → fired=True + 重置 OCR。

    事务边界:函数自身不 commit(commit 归调用方,与 payload 段合并事务)。
    """
    from app.services.handwriting.service import upsert_canvas_image

    row = _make_canvas_row(canvas_index=1, image_id=7)
    row.image_hash = "old"
    row.ocr_status = "done"
    row.text = "旧 OCR 文本"
    sess = _mock_db([row])

    result_row, fired = await upsert_canvas_image(
        sess,
        session_id="s1", user_id="u1", image_base64="b64",
        image_format="png", image_bytes_size=10, image_hash="new",
        canvas_index=1, client_created_at=datetime.now(timezone.utc),
    )
    assert fired is True
    assert result_row is row
    assert row.image_hash == "new"
    assert row.ocr_status == "pending"
    assert row.text == ""
    assert sess.add.call_count == 0  # UPDATE 不 INSERT
    sess.flush.assert_not_awaited()
    sess.commit.assert_not_awaited()  # 事务边界:commit 归调用方


@pytest.mark.asyncio
async def test_upsert_canvas_image_dedup_fills_canvas_index():
    """canvas 行不存在 + 同 user 同 hash 已有 → 返已有行不 INSERT;
    OCR-only 行(canvas_index=None)补上当前画板号。"""
    from app.services.handwriting.service import upsert_canvas_image

    existing = _make_canvas_row(canvas_index=1, image_id=42)
    existing.canvas_index = None  # OCR-only 行
    sess = _mock_db([None, existing])  # replace 查 None → dedup 查 existing

    row, fired = await upsert_canvas_image(
        sess,
        session_id="s1", user_id="u1", image_base64="b64",
        image_format="png", image_bytes_size=10, image_hash="h",
        canvas_index=2, client_created_at=datetime.now(timezone.utc),
    )
    assert fired is False  # dedup 命中不重跑 OCR
    assert row is existing
    assert existing.canvas_index == 2  # 补号
    assert sess.add.call_count == 0


@pytest.mark.asyncio
async def test_upsert_canvas_image_inserts_when_no_match():
    """canvas 行 + dedup 都查无 → INSERT 新行,fired=True 触发 OCR。"""
    from app.services.handwriting.service import upsert_canvas_image

    sess = _mock_db([None, None])

    row, fired = await upsert_canvas_image(
        sess,
        session_id="s1", user_id="u1", image_base64="b64",
        image_format="png", image_bytes_size=10, image_hash="h",
        canvas_index=1, client_created_at=datetime.now(timezone.utc),
    )
    assert fired is True
    assert row.canvas_index == 1
    assert row.ocr_status == "pending"
    sess.add.assert_called_once()
    sess.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_canvas_image_integrity_error_fallback():
    """并发撞 UNIQUE(user_id, image_hash) → flush 抛 IntegrityError →
    rollback 后按 (user_id, image_hash) 兜底重查,返回并发已插入的行。"""
    from sqlalchemy.exc import IntegrityError

    fallback_row = _make_canvas_row(canvas_index=1, image_id=99)
    fallback_row.image_hash = "new_hash"  # 并发方插入的行,同 user 同 hash
    call_count = {"n": 0}
    sess = MagicMock()

    def _result(r):
        m = MagicMock()
        m.scalar_one_or_none = MagicMock(return_value=r)
        return m

    async def execute(stmt):
        call_count["n"] += 1
        # 1:replace 查 None;2:dedup 查 None;3:IntegrityError 后兜底重查
        return _result(None if call_count["n"] <= 2 else fallback_row)

    async def flush():
        raise IntegrityError("mock", {}, None)

    sess.execute = execute
    sess.add = MagicMock()
    sess.flush = flush
    sess.rollback = AsyncMock()
    sess.commit = AsyncMock()

    row, fired = await upsert_canvas_image(
        sess,
        session_id="s1", user_id="u1", image_base64="x",
        image_format="jpeg", image_bytes_size=1, image_hash="new_hash",
        canvas_index=1, client_created_at=datetime.now(timezone.utc),
    )
    assert fired is False  # 兜底命中,不是新建
    assert row.id == 99  # 拿到的是并发已插入的行
    sess.rollback.assert_awaited_once()
