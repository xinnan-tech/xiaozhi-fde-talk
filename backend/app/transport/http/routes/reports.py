"""报告路由。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Response

from app.core.config_store import get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.services.reports.exporter import export as export_report
from app.services.reports.generator import get_or_generate
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.transport.http.dependencies import get_current_user

router = APIRouter(prefix="/interviews")


async def _own_session_or_404(session_id: str, user: CurrentUser):
    """校验访谈归属，返回 SessionState 或抛 404。"""
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    return state


@router.get("/{session_id}/report")
async def get_interview_report(
    session_id: str,
    force: bool = Query(False, description="Force regenerate, bypassing cache"),
    user: CurrentUser = Depends(get_current_user),
):
    """获取访谈报告（Markdown）。首次请求时惰性生成 + 落库；之后返回缓存。

    force=true 时跳过缓存——用于前端「重新生成报告」按钮，按当前 llm.output_language
    强制重跑（issue #82）。默认按当前缓存命中策略：语种切换不再触发无意义重生。

    若该会话仍有存活 runtime（在线或寄存），完成后通过 on_ready 把 report.ready
    帧经 runtime 的 WS 通道推给前端；前端据此可主动刷新报告页。无 runtime 则
    on_ready 直接 no-op——GET 同步返回里 status 已带结果。
    """
    await _own_session_or_404(session_id, user)
    rt = registry.get(session_id)

    async def on_ready(status: str) -> None:
        if rt is not None:
            await rt.push_report_ready(status)

    status_str, md = await get_or_generate(session_id, on_ready=on_ready, force=force)
    return {"status": status_str, "content_md": md}


@router.post("/{session_id}/export")
async def export_interview_report(
    session_id: str,
    format: str = "md",
    user: CurrentUser = Depends(get_current_user),
):
    """导出报告：format = md / html / word（pdf 后加）。

    错误响应统一走 I18nError：
    - FormatNotImplementedError (继承 I18nError, http_status=501)
    - ValueError           → HTTP_REPORT_FORMAT_UNSUPPORTED (http_status=400)
    - 其他 I18nError       → 直接冒泡
    """
    await _own_session_or_404(session_id, user)
    status_str, md = await get_or_generate(session_id)
    if status_str != "ready" or not md:
        raise I18nError(Keys.HTTP_REPORT_NOT_READY, http_status=409)
    # word 格式按 llm.output_language 选 ascii/eastAsia 字体；md/html 不读 language。
    # 与 generator.py:331-333 「一次性读 llm.output_language 全程共用」一致——避免
    # 导出与报告内容两个 lang 的「错位」（用户界面 en 但报告落库 zh_cn，word 仍按 zh_cn 选字体）。
    language = (
        get_config_store().get_sync("llm.output_language") or "en"
    ).strip().lower() or "en"
    try:
        data, media_type = await asyncio.to_thread(export_report, md, format, language)
    except I18nError:
        # FormatNotImplementedError (501) / 其它已结构化的 I18nError 直接冒泡，
        # 由 app.py:239 的 I18nError handler 转 {detail, code} 响应。
        raise
    except ValueError as e:
        raise I18nError(
            Keys.HTTP_REPORT_FORMAT_UNSUPPORTED, http_status=400,
            fmt=str(e), supported="md/html/word",
        )
    ext = "docx" if format == "word" else format
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="report.{ext}"'},
    )
