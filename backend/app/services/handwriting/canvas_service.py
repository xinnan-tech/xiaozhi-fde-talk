"""手写画板 state 服务层。

canvas_index 是前端自增键(1/2/3...),与 handwriting_images.id 独立——
同一行可同时持有 image + canvas_payload,改画板时改 payload + 可选改图。

payload hash 跳过防护:POST 进来与 DB 现存 payload hash 一致则跳过,不动
updated_at(由 onupdate 触发)与 client_updated_at。

owner 校验:操作方 user_id 必须与行 user_id 匹配,跨用户/跨 session 静默 no-op。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.db import SessionLocal
from app.persistence.models import HandwritingImage

logger = logging.getLogger(__name__)


def compute_canvas_payload_hash(payload: dict) -> str:
    """对 payload 做规范化序列化后 sha256——key 顺序无关。

    sort_keys=True 保证 dict 字段顺序变化不影响 hash(同一业务数据
    即使 Python dict 顺序不同也产生同一 hash)。
    """
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CanvasUpsertResult:
    """canvas payload UPSERT 结果。

    payload_skipped=True 表示 hash 与 DB 一致,跳过写(节省 DB 写);
    payload_updated=True 表示真改了 payload。两者互斥。
    """
    row: HandwritingImage
    payload_skipped: bool
    payload_updated: bool


async def upsert_canvas_payload(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    canvas_index: int,
    payload: dict,
) -> Optional[CanvasUpsertResult]:
    """upsert canvas payload:hash 同则跳过,不同则覆盖。

    找不到对应行返 None(由 handler 转 404)——canvas 与 image 一一映射,必须
    先 POST 图创建 image_id 对应行,才能 upsert canvas payload。

    image_hash / OCR 状态字段不在这条路径里——若同时携带 filedata,handler
    走 create_pending_image_auto 独立路径。
    """
    new_hash = compute_canvas_payload_hash(payload)
    # 找该 (session_id, user_id, canvas_index) 行
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
    if row.canvas_payload_hash == new_hash:
        return CanvasUpsertResult(row=row, payload_skipped=True, payload_updated=False)
    row.canvas_payload = payload
    row.canvas_payload_hash = new_hash
    await db.commit()
    return CanvasUpsertResult(row=row, payload_skipped=False, payload_updated=True)


async def upsert_canvas_payload_auto(
    *,
    session_id: str,
    user_id: str,
    canvas_index: int,
    payload: dict,
) -> Optional[CanvasUpsertResult]:
    """自动管理 session 的 upsert 版本。"""
    async with SessionLocal() as db:
        return await upsert_canvas_payload(
            db,
            session_id=session_id,
            user_id=user_id,
            canvas_index=canvas_index,
            payload=payload,
        )


async def list_canvases_auto(*, session_id: str, user_id: str) -> list[HandwritingImage]:
    """返该 session 该 user 所有画板(按 canvas_index 升序)。

    仅返 canvas_index 非 NULL 的行——纯 OCR 图(canvas_index=NULL)
    不算"画板",前端不需要看。WHERE canvas_index IS NOT NULL 把它们排除。
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(HandwritingImage)
            .where(
                HandwritingImage.session_id == session_id,
                HandwritingImage.user_id == user_id,
                HandwritingImage.canvas_index.is_not(None),
            )
            .order_by(
                HandwritingImage.canvas_index.asc(),
                HandwritingImage.id.asc(),
            )
        )
        return list(result.scalars().all())


async def delete_canvas_auto(
    *, session_id: str, user_id: str, canvas_index: int,
) -> Optional[int]:
    """按 (session_id, user_id, canvas_index) 删行。

    返 image_id(实际删除的行主键)或 None(不存在/归属不符)。
    handler 用 image_id 同步清理 state.handwriting_notes——canvas_index 是
    前端逻辑编号,与 image_id(DB 主键)不一定相等。
    幂等:重复删第二次返 None。
    """
    async with SessionLocal() as db:
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
        image_id = row.id
        await db.delete(row)
        await db.commit()
        return image_id


async def delete_canvases_batch_auto(
    *, session_id: str, user_id: str, canvas_indexes: list[int],
) -> list[int]:
    """批量按 canvas_index 列表删行。

    返实际删除的 image_id 列表(跨 session/跨 user 静默跳过)。
    一次 SQL 循环 DELETE,每个 canvas_index 单独 owner 校验。
    """
    if not canvas_indexes:
        return []
    deleted_ids: list[int] = []
    for idx in canvas_indexes:
        image_id = await delete_canvas_auto(
            session_id=session_id,
            user_id=user_id,
            canvas_index=idx,
        )
        if image_id is not None:
            deleted_ids.append(image_id)
    return deleted_ids
