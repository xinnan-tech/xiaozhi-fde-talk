"""手写笔记服务。

append 语义:每张图 1 行,按 (user_id, image_hash) 联合唯一索引判重。

依赖 services/handwriting/ocr_task._ocr_with_retry 由 handler 显式调起
(asyncio.create_task),不在本服务内启动——避免服务层拥有异步 task 生命周期。
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.note import HandwritingNote, OcrStatus
from app.persistence.db import SessionLocal
from app.persistence.models import HandwritingImage


def compute_image_hash(image_base64: str) -> str:
    """只算图本身字节 hash,不含 session/timestamp。

    sha256(base64.b64decode(image_base64)) → hex。用于跨用户隔离去重:
    同一用户的同一张图不会因重试/连点产生重复行;跨用户不去重,防数据归属混乱。

    如果调用方已有解码后的 image_bytes,改用 compute_image_hash_from_bytes 复用,
    避免 10MB 上限图的双重 b64decode。
    """
    image_bytes = base64.b64decode(image_base64)
    return hashlib.sha256(image_bytes).hexdigest()


def compute_image_hash_from_bytes(image_bytes: bytes) -> str:
    """复用已解码的字节流算 hash——handler 内 b64decode 一次后给两个用途。"""
    return hashlib.sha256(image_bytes).hexdigest()


def sniff_image_format(image_bytes: bytes) -> str:
    """按 magic bytes 嗅探图片格式,只认 jpeg / png / bmp。"""
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith(b"BM"):
        return "bmp"
    return ""


async def create_pending_image(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    image_base64: str,
    image_hash: str,
    image_format: str,
    image_bytes_size: int,
    client_created_at: datetime,
) -> HandwritingImage:
    """落库 (ocr_status=pending),返回新行 ORM 句柄(handler 拿 id 启 OCR task)。

    按 (session_id, user_id, image_hash) 判重——同 session 内同字节图去重,
    避免重复启 OCR task。跨 session 不去重,各自独立存储(防跨用户/跨 session
    数据归属混乱)。
    """
    existing = await db.execute(
        select(HandwritingImage).where(
            HandwritingImage.session_id == session_id,
            HandwritingImage.user_id == user_id,
            HandwritingImage.image_hash == image_hash,
        ).limit(1)
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        return existing_row

    row = HandwritingImage(
        session_id=session_id,
        user_id=user_id,
        image_base64=image_base64,
        image_format=image_format,
        image_bytes_size=image_bytes_size,
        ocr_status="pending",
        text="",
        retry_count=0,
        image_hash=image_hash,
        client_created_at=client_created_at,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # 并发撞 UNIQUE(user_id, image_hash)——回滚后按同 session+hash 兜底重查
        await db.rollback()
        existing = await db.execute(
            select(HandwritingImage).where(
                HandwritingImage.session_id == session_id,
                HandwritingImage.user_id == user_id,
                HandwritingImage.image_hash == image_hash,
            ).limit(1)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is None:
            raise
        return existing_row
    return row


async def replace_canvas_image(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    image_base64: str,
    image_format: str,
    image_bytes_size: int,
    image_hash: str,
    canvas_index: int,
    client_created_at: datetime,
) -> Optional[tuple[HandwritingImage, bool]]:
    """同 canvas_index 改图(image_hash 变了):UPDATE 现有行的 image 字段。

    返回 (row, ocr_task_fired) 或 None(canvas 行不存在——走 create_pending_image_auto 兜底)。
    ocr_task_fired=True 表示 image_hash 与 DB 不一致,需要后台重跑 OCR;
    False 表示 hash 一致(image_base64 内容相同),跳过 OCR。

    保留原 image_id(画板号 = canvas_index,DB 主键 = image_id 一一对应稳定)。
    """
    from sqlalchemy import update as sa_update
    result = await db.execute(
        select(HandwritingImage).where(
            HandwritingImage.session_id == session_id,
            HandwritingImage.user_id == user_id,
            HandwritingImage.canvas_index == canvas_index,
        ).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    ocr_task_fired = row.image_hash != image_hash
    row.image_base64 = image_base64
    row.image_format = image_format
    row.image_bytes_size = image_bytes_size
    row.image_hash = image_hash
    row.client_created_at = client_created_at
    if ocr_task_fired:
        # 图变了 → 重置 OCR 状态 + 清旧文本,等后台 task 重跑
        row.ocr_status = "pending"
        row.text = ""
        row.retry_count = 0
        row.injected_at = None
    await db.commit()
    return (row, ocr_task_fired)


async def replace_canvas_image_auto(
    *,
    session_id: str,
    user_id: str,
    image_base64: str,
    image_format: str,
    image_bytes_size: int,
    image_hash: str,
    canvas_index: int,
    client_created_at: datetime,
) -> Optional[tuple[HandwritingImage, bool]]:
    """自动管理 session 版本。"""
    async with SessionLocal() as db:
        return await replace_canvas_image(
            db,
            session_id=session_id,
            user_id=user_id,
            image_base64=image_base64,
            image_format=image_format,
            image_bytes_size=image_bytes_size,
            image_hash=image_hash,
            canvas_index=canvas_index,
            client_created_at=client_created_at,
        )


async def create_pending_image_auto(
    *,
    session_id: str,
    user_id: str,
    image_base64: str,
    image_hash: str,
    image_format: str,
    image_bytes_size: int,
    client_created_at: datetime,
    canvas_index: int | None = None,
) -> tuple[HandwritingImage, bool]:
    """自动管理 session。返回 (row, created) ——created=False 表示去重命中。

    canvas_index:画板号(可选)——canvas 与 image 一一映射时,handler 显式传。
    新建行直接写入;命中 dedup 时若 canvas_index 为 NULL 也补上(已存在行
    不会有 canvas_index,但 POST 画板时必须知道当前是几号画板)。

    dedup 按 (session_id, user_id, image_hash)——同 session 内同字节图去重,
    避免重复启 OCR task。跨 session 不去重,各自独立存储。

    跨画板同图拦截:UNIQUE(user_id, image_hash) 禁止同用户跨
    canvas_index 复用同一图字节。
    """
    async with SessionLocal() as db:
        # 先查 dedup,避免无谓 flush
        existing = await db.execute(
            select(HandwritingImage).where(
                HandwritingImage.session_id == session_id,
                HandwritingImage.user_id == user_id,
                HandwritingImage.image_hash == image_hash,
            ).limit(1)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            # dedup 命中 + canvas_index 未设:补上(OCR-only 行升级为画板)
            if canvas_index is not None and existing_row.canvas_index is None:
                existing_row.canvas_index = canvas_index
                await db.commit()
                return existing_row, False
            # 跨画板同图:UNIQUE(user_id, image_hash) 会拒 INSERT,这里提前抛
            if (
                canvas_index is not None
                and existing_row.canvas_index is not None
                and existing_row.canvas_index != canvas_index
            ):
                raise ValueError(
                    f"用户已有相同图片字节(image_id={existing_row.id}, "
                    f"canvas_index={existing_row.canvas_index}),"
                    f"不允许跨画板复用,目标 canvas_index={canvas_index}"
                )
            return existing_row, False
        row = HandwritingImage(
            session_id=session_id,
            user_id=user_id,
            image_base64=image_base64,
            image_format=image_format,
            image_bytes_size=image_bytes_size,
            ocr_status="pending",
            text="",
            retry_count=0,
            image_hash=image_hash,
            canvas_index=canvas_index,
            client_created_at=client_created_at,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # 并发撞 UNIQUE(session_id, user_id, canvas_index)——
            # 回滚后按该 canvas_index 兜底查现存行
            existing = await db.execute(
                select(HandwritingImage).where(
                    HandwritingImage.session_id == session_id,
                    HandwritingImage.user_id == user_id,
                    HandwritingImage.canvas_index == canvas_index,
                ).limit(1)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row is None:
                raise
            return existing_row, False
        return row, True


async def list_handwriting_images_auto(
    *, session_id: str,
) -> list[HandwritingNote]:
    """报告页用:按 created_at 升序拉全部手写原图 + OCR 文本。"""
    async with SessionLocal() as db:
        result = await db.execute(
            select(HandwritingImage)
            .where(HandwritingImage.session_id == session_id)
            .order_by(HandwritingImage.created_at.asc())
        )
        rows = result.scalars().all()
        return [
            HandwritingNote(
                image_id=r.id,
                session_id=r.session_id,
                user_id=r.user_id,
                image_base64=r.image_base64,
                image_format=r.image_format,
                image_bytes_size=r.image_bytes_size,
                ocr_status=OcrStatus(r.ocr_status),
                text=r.text or "",
                created_at=r.created_at,
            )
            for r in rows
        ]


async def get_by_id_auto(image_id: int) -> Optional[HandwritingImage]:
    """OCR task 用:取一行更新状态。"""
    async with SessionLocal() as db:
        return await db.get(HandwritingImage, image_id)


async def delete_handwriting_image_auto(
    *, session_id: str, user_id: str, image_id: int,
) -> bool:
    """按 image_id 删除单张图。owner 校验:只删当前用户的图,跨用户 / 不属于该 session 不删。

    返回 True=实际删了,False=不存在或归属不符(都是 no-op,handler 不报错)。
    幂等性:重复删同一个 id 第二次返 False,handler 同样 200 成功。
    """
    from sqlalchemy import delete as sa_delete

    async with SessionLocal() as db:
        # 先查归属,避免 DELETE 没匹配返 affected=0 时无法区分「不存在」与「权限不符」
        row = await db.get(HandwritingImage, image_id)
        if row is None or row.user_id != user_id or row.session_id != session_id:
            return False
        await db.delete(row)
        await db.commit()
        return True


async def delete_handwriting_images_batch_auto(
    *, session_id: str, user_id: str, image_ids: list[int],
) -> list[int]:
    """批量删除:只删 (session_id, user_id) 双匹配的图,跨 session/跨用户跳过。
    幂等:已删除的 id 跳过(返的 deleted_ids 不含)。
    """
    if not image_ids:
        return []
    from sqlalchemy import delete as sa_delete

    async with SessionLocal() as db:
        # 先 SELECT IN(...) 拿回当前已存在且归属匹配的 id
        result = await db.execute(
            select(HandwritingImage.id).where(
                HandwritingImage.id.in_(image_ids),
                HandwritingImage.user_id == user_id,
                HandwritingImage.session_id == session_id,
            )
        )
        owned_ids = [r for r in result.scalars().all()]
        if not owned_ids:
            return []
        await db.execute(
            sa_delete(HandwritingImage).where(
                HandwritingImage.id.in_(owned_ids),
                HandwritingImage.user_id == user_id,
                HandwritingImage.session_id == session_id,
            )
        )
        await db.commit()
        return owned_ids