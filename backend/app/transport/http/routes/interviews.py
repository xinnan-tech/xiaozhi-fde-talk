"""访谈路由。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.exceptions import IllegalTransitionError
from app.domain.auth import CurrentUser
from app.domain.session import SessionStatus
from app.services.coaching.engine import TERMINAL_SESSION_STATUSES
from app.services.coaching.first_batch import generate_first_batch
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import (
    CreateInterviewRequest,
    InterviewStatisticsResponse,
    UpdateInterviewRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews")


_STATUS_TYPE = {
    "created": "info",
    "setting_up": "info",
    "in_progress": "info",
    "suspended": "warning",
    "ended": "success",
    "extracting": "info",
    "done": "success",
}


def _utc_isoformat(value: datetime | None) -> str | None:
    """将数据库时间按 UTC 明确输出，供客户端安全本地化显示。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _session_summary(rec, tpl) -> dict:
    """ORM InterviewRecord + Template → summary dict（含派生计数与展示字段）。

    字段集合见 Task A3 描述。
    """
    base_info = rec.base_info or {}
    items = rec.coaching_items or []
    ignored_ids = set(rec.ignored_ids or [])

    pending_count = sum(1 for it in items if it.get("status") in ("todo", "new"))
    covered_count = sum(1 for it in items if it.get("status") == "done")
    coverage_index = rec.coverage_index or {}
    asked_count = sum(
        1 for it in items
        if it.get("status") == "done" and len(coverage_index.get(it["id"], [])) > 0
    )

    return {
        "id": rec.id,
        "template_id": rec.template_id,
        "template_version": rec.template_version,
        "template_icon_url": tpl.icon_url if tpl else "",
        "status": rec.status,
        "status_type": _STATUS_TYPE.get(rec.status, "info"),
        "base_info": base_info,
        "title": base_info.get("project") or "未命名访谈",
        "interviewee": base_info.get("interviewee", ""),
        "type": tpl.name if tpl else "",
        "recent_time": _utc_isoformat(max(
            filter(None, [rec.created_at, rec.started_at, rec.ended_at])
        )) if any([rec.created_at, rec.started_at, rec.ended_at]) else None,
        "goal": rec.goal,
        "pending_count": pending_count,
        "covered_count": covered_count,
        "asked_count": asked_count,
        "ignored_count": len(ignored_ids),
        "total_count": len(items),
        "created_at": _utc_isoformat(rec.created_at),
        "started_at": _utc_isoformat(rec.started_at),
        "ended_at": _utc_isoformat(rec.ended_at),
    }


async def _summary_from_session_id(session_id: str) -> dict:
    """根据 session_id 取 ORM + 模板，返回 _session_summary dict。

    找不到会话则抛 404（与路由层语义一致）。
    """
    from app.persistence.db import SessionLocal
    from app.persistence.models import InterviewRecord
    from app.services.template.loader import get_template
    async with SessionLocal() as db:
        rec = await db.get(InterviewRecord, session_id)
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
        tpl = get_template(rec.template_id)
        return _session_summary(rec, tpl)


def _state_detail(state) -> dict:
    s = state.session
    return {
        "id": s.id,
        "template_id": s.template_id,
        "template_version": s.template_version,
        "status": s.status.value,
        "base_info": s.base_info,
        "goal": s.goal,
        "first_batch_generated": s.first_batch_generated,
        "consumed_seq": s.consumed_seq,
        "created_at": _utc_isoformat(s.created_at),
        "started_at": _utc_isoformat(s.started_at),
        "ended_at": _utc_isoformat(s.ended_at),
        "items": [it.model_dump(mode="json") for it in state.items],
        "skipped_ids": sorted(state.skipped_ids),
        "ignored_ids": sorted(state.ignored_ids),
        "coverage": state.coverage,
        "transcript": [seg.model_dump(mode="json") for seg in state.transcript],
    }


@router.post("")
async def create_interview(
    req: CreateInterviewRequest,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        state = await manager.create(user.user_id, req.template_id, req.base_info, req.goal)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    return await _summary_from_session_id(state.session.id)


@router.get("")
async def list_interviews(
    status: Optional[str] = Query(
        None,
        description="逗号分隔：created/setting_up/in_progress/suspended/ended/extracting/done",
    ),
    user: CurrentUser = Depends(get_current_user),
):
    statuses: Optional[list[SessionStatus]] = None
    if status:
        try:
            statuses = [
                SessionStatus(s.strip()) for s in status.split(",") if s.strip()
            ]
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知状态：{e}")
    pairs = await manager.list_summaries_for_user(user.user_id, statuses=statuses)
    return {"items": [_session_summary(rec, tpl) for rec, tpl in pairs]}


@router.get("/statistics", response_model=InterviewStatisticsResponse)
async def interview_statistics(
    user: CurrentUser = Depends(get_current_user),
):
    """首页四张统计卡聚合数字（snake_case keys）。"""
    return await manager.statistics_for_user(user.user_id)


@router.get("/{session_id}")
async def get_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    # 资源隔离：不是本人的访谈一律 404（不泄露存在性）
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    return _state_detail(state)


@router.patch("/{session_id}")
async def update_interview(
    session_id: str,
    req: UpdateInterviewRequest,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    try:
        await manager.update(session_id, req.base_info, req.goal)
    except IllegalTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return await _summary_from_session_id(session_id)


# 后台拆除任务的强引用：create_task 只留弱引用，事件循环也只持待执行任务的
# 引用——任务一旦 await 挂起（终算 LLM 可达 135s），没有任何一方持有它，
# GC 随时可能把连 await 中的协程一起收走。这里持有到任务结束为止。
_teardown_tasks: set[asyncio.Task] = set()


def _teardown_runtime(session_id: str) -> None:
    """后台拆除 runtime（若有）：coaching 终算是一次 LLM 调用（超时上限 135s，= coach.llm_timeout_s × 3），
    不能挂在 HTTP 请求上。拆除完成前 runtime 仍留在 registry，进程关停的
    shutdown drain 能找到并等它跑完。
    """
    rt = registry.get(session_id)
    if rt is None:
        return

    async def _run() -> None:
        try:
            await rt.end()
        except Exception:  # noqa: BLE001
            logger.exception("结束后拆除 runtime 失败：session=%s", session_id)
        finally:
            registry.drop(session_id)

    task = asyncio.create_task(_run())
    _teardown_tasks.add(task)
    task.add_done_callback(_teardown_tasks.discard)


@router.post("/{session_id}/first-batch")
async def first_batch_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """生成/返回首批评量（幂等）。

    有 runtime（在线或寄存）→ 经 runtime 引擎生成：同一 state 对象 + 引擎锁，
    在线时结果顺带经 WS 推送。无 runtime → 在 DB 状态上生成（in-flight 锁）。
    已结束 / 已生成 / 对话已开始 → 直接返回当前清单，不调 LLM。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    if state.session.status in TERMINAL_SESSION_STATUSES:
        return _first_batch_response(state)
    rt = registry.get(session_id)
    if rt is not None:
        await rt.engine.first_generate()
        return _first_batch_response(rt.state)
    state = await generate_first_batch(session_id) or state
    return _first_batch_response(state)


def _first_batch_response(state) -> dict:
    return {
        "generated": state.session.first_batch_generated,
        "items": [it.model_dump(mode="json") for it in state.items],
    }


@router.post("/{session_id}/end")
async def end_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """结束访谈（未建立 WS 连接也可结束，如暂停态直接点「结束访谈」）。

    与 WS end 语义一致：manager.end 先把 status 落盘成 ended（请求返回后列表
    即时可见），runtime 收尾放后台任务。若另一客户端仍连着该会话，其连接会在
    runtime 拆除后失效。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    try:
        await manager.end(session_id)
    except IllegalTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    _teardown_runtime(session_id)
    return await _summary_from_session_id(session_id)


@router.delete("/{session_id}")
async def delete_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    try:
        await manager.delete(session_id)
    except IllegalTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/ignore")
async def ignore_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    await manager.set_item_status(session_id, item_id, "ignore")
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/unignore")
async def unignore_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    await manager.set_item_status(session_id, item_id, "unignore")
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/skip")
async def skip_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    await manager.set_item_status(session_id, item_id, "skip")
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/unskip")
async def unskip_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    await manager.set_item_status(session_id, item_id, "unskip")
    return {"ok": True}
