"""手写 OCR 后台 task。

handler 立刻落库 + 立刻返 200,同时 asyncio.create_task(_ocr_with_retry)
启动后台 task 跑 OCR,最多 5 轮重试每次 30s。失败累计转 failed 不复活。
进程重启会丢进行中的 task,DB 行卡 pending/failed。
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone

from app.adapters.ocr.factory import get_handwriting_ocr
from app.domain.note import OcrStatus
from app.persistence.db import SessionLocal
from app.persistence.models import HandwritingImage

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_S = 30
_MAX_RETRY = 5
_OCR_TIMEOUT_S = 30  # 单次 provider.recognize 超时——防 TCP hang 长持锁


async def _ocr_with_retry(image_id: int, session_id: str) -> None:
    """对单张图跑 OCR,最多 5 轮重试每次 30s。失败累计转 failed。

    重画保护:记首轮 image_hash,变了即退出(让新 task 接管)。
    """
    provider = get_handwriting_ocr()
    image_hash_at_start: str | None = None
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            # 1) 短 session:fetch 行 + 校验 + 释放连接
            async with SessionLocal() as session:
                img = await session.get(HandwritingImage, image_id)
                if img is None:
                    return
                if image_hash_at_start is None:
                    image_hash_at_start = img.image_hash
                elif img.image_hash != image_hash_at_start:
                    logger.info(
                        "OCR 跳过(画板已重画)image_id=%s", image_id,
                    )
                    return
                if img.ocr_status == OcrStatus.DONE.value:
                    logger.info(
                        "OCR 跳过(已被其他 task 完成)image_id=%s", image_id,
                    )
                    return
                try:
                    image_bytes = base64.b64decode(img.image_base64)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "OCR image_base64 decode 失败:image_id=%s err=%s",
                        image_id, e,
                    )
                    img.ocr_status = OcrStatus.FAILED.value
                    img.retry_count = attempt
                    await session.commit()
                    return
                if len(image_bytes) != img.image_bytes_size:
                    logger.warning(
                        "OCR image_bytes_size 不一致:image_id=%s "
                        "declared=%s decoded=%s",
                        image_id, img.image_bytes_size, len(image_bytes),
                    )
                    img.ocr_status = OcrStatus.FAILED.value
                    img.retry_count = attempt
                    await session.commit()
                    return

            # 2) 调 provider(不持 DB 连接,防止长跑任务占住连接池)
            try:
                text = await asyncio.wait_for(
                    provider.recognize(image_bytes), timeout=_OCR_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"OCR 超过 {_OCR_TIMEOUT_S}s 未响应")

            # 3) 短 session:写结果 + 释放连接
            async with SessionLocal() as session:
                img = await session.get(HandwritingImage, image_id)
                if img is None:
                    return
                img.text = text
                img.ocr_status = OcrStatus.DONE.value
                img.retry_count = attempt
                img.injected_at = datetime.now(timezone.utc)
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "OCR 失败 image_id=%s attempt=%s err=%s",
                image_id, attempt, e,
            )
            if attempt >= _MAX_RETRY:
                # 最后一轮失败:标 failed
                try:
                    async with SessionLocal() as session:
                        img = await session.get(HandwritingImage, image_id)
                        if img is not None and img.ocr_status != OcrStatus.DONE.value:
                            img.ocr_status = OcrStatus.FAILED.value
                            img.retry_count = attempt
                            await session.commit()
                except Exception as commit_err:  # noqa: BLE001
                    logger.warning(
                        "标记 ocr_status=failed 失败:image_id=%s err=%s",
                        image_id, commit_err,
                    )
                return
            await asyncio.sleep(_RETRY_INTERVAL_S)
            continue

        # DB 已 done,推 state。失败不抛——DB 已落,镜像列 cold start 可恢复。
        try:
            from app.services.sessions.runtime import registry

            runtime = registry.get(session_id)
            if runtime is not None:
                await runtime.inject_handwriting_note(
                    image_id=image_id, text=text,
                )
            else:
                # runtime 已销毁,直接刷镜像列;走 mutate_state_auto 持锁 RMW
                # 串行化多 OCR task 并发,杜绝后写覆盖前写。
                from app.domain.session_state import HandwritingNoteSegment
                from app.persistence.repositories.interview import interview_repo

                def _append(state):
                    if any(n.image_id == image_id for n in state.handwriting_notes):
                        return False
                    state.handwriting_notes.append(HandwritingNoteSegment(
                        image_id=image_id,
                        text=text,
                        injected_at=datetime.now(timezone.utc),
                    ))
                    return True

                await interview_repo.mutate_state_auto(
                    session_id, _append, fields={"notes"},
                )
        except Exception as inject_err:  # noqa: BLE001
            logger.warning(
                "OCR state 注入失败 image_id=%s err=%s", image_id, inject_err,
            )
        return
