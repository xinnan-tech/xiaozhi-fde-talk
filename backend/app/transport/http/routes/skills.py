"""skill 路由（Phase 10 MVP）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.services.skill.executor import invoke_skill
from app.services.skill.registry import list_public_skills
from app.transport.http.dependencies import get_current_user, require_admin
from app.transport.http.schemas import InvokeSkillRequest

router = APIRouter()


@router.get("/skills")
async def skills_list(_: CurrentUser = Depends(get_current_user)):
    """列出内置 skill。MVP 仅暴露后端注册的安全 skill。"""
    return {"items": list_public_skills()}


@router.post("/internal/skills/{skill_id}/invoke")
async def invoke_internal_skill(
    skill_id: str,
    req: InvokeSkillRequest,
    _: CurrentUser = Depends(require_admin),
):
    """内部 skill 调用接口；报告生成主要走 executor 直接调用。

    会触发真实 LLM 调用（烧额度），仅 admin 可调。
    """
    result = await invoke_skill(skill_id, req.inputs)
    if not result.ok:
        raise I18nError(
            Keys.HTTP_SKILL_INVOKE_FAILED, http_status=404,
            reason=result.error or "",
        )
    return result.to_dict()
