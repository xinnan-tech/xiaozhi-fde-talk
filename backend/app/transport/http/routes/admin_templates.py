"""admin 模板管理：列表 / 新建 / 全量保存 / 删除 / AI 生成。

数据与校验都在 services/template/loader.py（缓存 + DB）；本层只做
参数形态校验（路径 id 与 body id 一致）+ 鉴权 + 响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.domain.template import Template
from app.services.template import generator, loader
from app.transport.http.dependencies import require_admin
from app.transport.http.schemas import AdminTemplateSummary, TemplateGenerateRequest

router = APIRouter(prefix="/admin/templates", tags=["admin"])


@router.get("", response_model=list[AdminTemplateSummary])
async def list_templates(
    _admin: CurrentUser = Depends(require_admin),
) -> list[AdminTemplateSummary]:
    return [AdminTemplateSummary(**item) for item in await loader.admin_list()]


@router.post("", response_model=Template)
async def create_template(
    body: Template,
    _admin: CurrentUser = Depends(require_admin),
) -> Template:
    return await loader.create_template(body)


@router.post("/generate", response_model=Template)
async def generate_template(
    body: TemplateGenerateRequest,
    _admin: CurrentUser = Depends(require_admin),
) -> Template:
    """AI 一句话生成模板。只生成不落库（落库仍走 POST /admin/templates），
    LLM 未配置 / 超时 / 输出不合规的错误原样抛给前端提示。"""
    return await generator.generate_template(body.brief)


@router.put("/{template_id}", response_model=Template)
async def update_template(
    template_id: str,
    body: Template,
    _admin: CurrentUser = Depends(require_admin),
) -> Template:
    if template_id != body.id:
        raise I18nError(
            Keys.TEMPLATE_INVALID_ID_MISMATCH, http_status=422,
            path=template_id, body=body.id,
        )
    return await loader.update_template(body)


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, bool]:
    await loader.delete_template(template_id)
    return {"ok": True}
