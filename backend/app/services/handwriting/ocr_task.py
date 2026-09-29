"""手写 OCR 后台 task。

handler 立刻落库 + 立刻返 200(POST 同步),同时 `asyncio.create_task(_ocr_with_retry)`
启动后台 task 跑 OCR。后台 task 最多 5 轮重试,每次失败间隔 30s。

进程重启会丢进行中的 task,DB 行的 ocr_status 卡 pending/failed,不复活(失败就失败)。
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone

from app.adapters.ocr.factory import get_handwriting_ocr
from app.persistence.db import SessionLocal
from app.persistence.models import HandwritingImage

logger = logging.getLogger(__name__)

_RETRY_INTERVAL_S = 30
_MAX_RETRY = 5  # 最多跑 5 轮(失败的也计 1 轮)


async def _ocr_with_retry(image_id: int, session_id: str) -> None:
    """对单张图跑 OCR + 最多 5 次重试,每次失败间隔 30s。

    成功路径:UPDATE ocr_status=done + text + retry_count + 推 state.handwriting_notes
    失败路径:retry_count+=1,全部失败转 ocr_status=failed 后不再跑

    `session_id` 由 handler 传入(task 不查 DB 拿,避免额外一次 DB hit)

    重画保护:记首轮 image_hash,变了即退出。
    """
    provider = get_handwriting_ocr()
    image_hash_at_start: str | None = None
    for attempt in range(1, _MAX_RETRY + 1):
        text: str = ""
        try:
            async with SessionLocal() as session:
                img = await session.get(HandwritingImage, image_id)
                if img is None:
                    return
                # 重画检测:hash 变了即退出
                if image_hash_at_start is None:
                    image_hash_at_start = img.image_hash
                elif img.image_hash != image_hash_at_start:
                    logger.info(
                        "OCR 跳过(画板已重画)image_id=%s old=%s new=%s",
                        image_id, image_hash_at_start, img.image_hash,
                    )
                    return
                if img.ocr_status == "done":
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
                    img.ocr_status = "failed"
                    img.retry_count = attempt
                    await session.commit()
                    return
                if len(image_bytes) != img.image_bytes_size:
                    logger.warning(
                        "OCR image_bytes_size 不一致:image_id=%s "
                        "declared=%s decoded=%s(可能 base64 padding 注入)",
                        image_id, img.image_bytes_size, len(image_bytes),
                    )
                    img.ocr_status = "failed"
                    img.retry_count = attempt
                    await session.commit()
                    return
                text = await provider.recognize(image_bytes)
                img.text = text
                img.ocr_status = "done"
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
                        if img is not None and img.ocr_status != "done":
                            img.ocr_status = "failed"
                            img.retry_count = attempt
                            await session.commit()
                except Exception as commit_err:  # noqa: BLE001
                    logger.warning(
                        "标记 ocr_status=failed 失败：image_id=%s err=%s",
                        image_id, commit_err,
                    )
                return
            # 还有下次:等 30s 后重试(期间用户可能重画 → 下一轮 fetch 会发现 image_hash 变了)
            await asyncio.sleep(_RETRY_INTERVAL_S)
            continue
        # DB 已 done;state 注入失败不触发 OCR 重跑(行 done,重跑立即跳过)。
        # 注入失败也不抛:DB 已 done,镜像列下次 cold start 仍能拉到,丢的只是
        # in-memory state 的实时可见性,可接受。
        try:
            from app.services.sessions.runtime import registry

            runtime = registry.get(session_id)
            if runtime is not None:
                await runtime.inject_handwriting_note(
                    image_id=image_id, text=text,
                )
            else:
                # runtime 已销毁(会话结束 / idle 超时)— 直接刷 state 镜像列,
                # 避免 _build_user 看不到这条 OCR 文本。走 mutate_state_auto
                # 持锁做 RMW:多 OCR task 并发时,get + append + save 在锁内
                # 串行化,杜绝后写覆盖前写。
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

                appended = await interview_repo.mutate_state_auto(
                    session_id, _append, fields={"notes"},
                )
                if appended:
                    logger.info(
                        "OCR 成功 image_id=%s attempt=%s(直接刷镜像列,runtime 已销毁)",
                        image_id, attempt,
                    )
                    return
                # dedup 命中:行已存在,不算真成功,日志加后缀便于排查
                logger.info(
                    "OCR 跳过(镜像列已有同 image_id 段)image_id=%s attempt=%s",
                    image_id, attempt,
                )
                return
        except Exception as inject_err:  # noqa: BLE001
            logger.warning(
                "OCR state 注入失败 image_id=%s attempt=%s err=%s "
                "(DB 已 done,后续 cold start 可恢复)",
                image_id, attempt, inject_err,
            )
            return
        logger.info("OCR 成功 image_id=%s attempt=%s", image_id, attempt)
        return