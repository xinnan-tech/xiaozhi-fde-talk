"""访谈路由。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.exceptions import IllegalTransitionError
from app.domain.auth import CurrentUser
from app.services.coaching.engine import TERMINAL_SESSION_STATUSES
from app.services.coaching.first_batch import generate_first_batch
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import CreateInterviewRequest, UpdateInterviewRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews")


def _session_summary(s) -> dict:
    return {
        "id": s.id,
        "template_id": s.template_id,
        "template_version": s.template_version,
        "status": s.status.value,
        "base_info": s.base_info,
        "goal": s.goal,
        "created_at": s.created_at,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
    }


def _state_detail(state) -> dict:
    s = state.session
    return {
        "id": s.id,
        "template_id": s.template_id,
        "template_version": s.template_version,
        "status": s.status.value,
        "user_id": s.user_id,
        "base_info": s.base_info,
        "goal": s.goal,
        "first_batch_generated": s.first_batch_generated,
        "consumed_seq": s.consumed_seq,
        "created_at": s.created_at,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
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
    return _session_summary(state.session)


@router.get("")
async def list_interviews(user: CurrentUser = Depends(get_current_user)):
    sessions = await manager.list_for_user(user.user_id)
    return {"items": [_session_summary(s) for s in sessions]}


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
        state = await manager.update(session_id, req.base_info, req.goal)
    except IllegalTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _session_summary(state.session)


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
        state = await manager.end(session_id)
    except IllegalTransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    _teardown_runtime(session_id)
    return _session_summary(state.session)


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
