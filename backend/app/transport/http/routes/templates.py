"""模板路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.services.template.loader import get_template, list_templates
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import TemplateListResponse, TemplateSummary

router = APIRouter(prefix="/templates")


@router.get("", response_model=TemplateListResponse)
async def templates_list(_: CurrentUser = Depends(get_current_user)):
    items = [
        TemplateSummary(
            id=t.id, name=t.name, icon_url=t.icon_url,
            icon_alt=t.icon_alt, version=t.version,
        )
        for t in list_templates()
    ]
    return TemplateListResponse(items=items)


@router.get("/{template_id}")
async def template_detail(
    template_id: str,
    version: str | None = None,
    _: CurrentUser = Depends(get_current_user),
):
    tpl = get_template(template_id)
    if tpl is None or (version is not None and tpl.version != version):
        raise I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
    return tpl
