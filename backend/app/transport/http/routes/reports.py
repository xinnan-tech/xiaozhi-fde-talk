"""报告路由。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.domain.auth import CurrentUser
from app.services.reports.exporter import FormatNotImplementedError, export as export_report
from app.services.reports.generator import get_or_generate
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
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
    """获取访谈报告（Markdown）。首次请求时惰性生成 + 落库；之后返回缓存。

    若该会话仍有存活 runtime（在线或寄存），完成后通过 on_ready 把 report.ready
    帧经 runtime 的 WS 通道推给前端；前端据此可主动刷新报告页。无 runtime 则
    on_ready 直接 no-op——GET 同步返回里 status 已带结果。
    """
    await _own_session_or_404(session_id, user)
    rt = registry.get(session_id)

    async def on_ready(status: str) -> None:
        if rt is not None:
            await rt.push_report_ready(status)

    status_str, md = await get_or_generate(session_id, on_ready=on_ready)
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
    except FormatNotImplementedError as e:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content={"ok": False, "code": "not_implemented", "format": e.fmt},
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    ext = "docx" if format == "word" else format
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report.{ext}"'},
    )
