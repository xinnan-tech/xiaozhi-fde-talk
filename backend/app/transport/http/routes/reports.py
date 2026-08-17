"""报告路由。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.domain.auth import CurrentUser
from app.services.reports.exporter import export as export_report
from app.services.reports.generator import get_or_generate
from app.services.sessions.manager import manager
from app.transport.http.dependencies import get_current_user

router = APIRouter(prefix="/interviews")


async def _own_session_or_404(session_id: str, user: CurrentUser):
    """校验访谈归属，返回 SessionState 或抛 404。"""
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "访谈不存在")
    return state


@router.get("/{session_id}/report")
async def get_interview_report(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """获取访谈报告（Markdown）。首次请求时惰性生成 + 落库；之后返回缓存。"""
    await _own_session_or_404(session_id, user)
    status_str, md = await get_or_generate(session_id)
    return {"status": status_str, "content_md": md}


@router.post("/{session_id}/export")
async def export_interview_report(
    session_id: str,
    format: str = "md",
    user: CurrentUser = Depends(get_current_user),
):
    """导出报告：format = md / html / word（pdf 后加）。"""
    await _own_session_or_404(session_id, user)
    status_str, md = await get_or_generate(session_id)
    if status_str != "ready" or not md:
        raise HTTPException(status.HTTP_409_CONFLICT, "报告尚未就绪")
    try:
        data, media_type = await asyncio.to_thread(export_report, md, format)
    except NotImplementedError as e:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    ext = "docx" if format == "word" else format
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report.{ext}"'},
    )
