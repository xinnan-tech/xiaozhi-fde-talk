"""admin REST：GET/PUT /api/v1/admin/config（系统配置）。

消费 Task 1 的 ConfigStore + SENSITIVE_KEYS。
- GET 全部/单分组：敏感字段返 null（防泄漏）
- PUT 分组：未知 key 拒绝（422），敏感字段空值跳过（不动 DB）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.config_store import ALL_B_KEYS, get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import require_admin

router = APIRouter(prefix="/admin/config", tags=["admin"])

_GROUPS = ("llm", "asr", "ocr", "coach", "auth", "session")


@router.get("")
async def get_all_config(
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, dict[str, Any]]:
    store = get_config_store()
    return {g: await store.get_group(g) for g in _GROUPS}


@router.get("/{group}")
async def get_group_config(
    group: str,
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    if group not in _GROUPS:
        raise I18nError(
            Keys.HTTP_ADMIN_CONFIG_GROUP_NOT_FOUND, http_status=404, group=group,
        )
    return await get_config_store().get_group(group)


@router.put("/{group}")
async def put_group_config(
    group: str,
    body: dict[str, Any],
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    if group not in _GROUPS:
        raise I18nError(
            Keys.HTTP_ADMIN_CONFIG_GROUP_NOT_FOUND, http_status=404, group=group,
        )

    allowed_keys = {k.split(".", 1)[1] for k in ALL_B_KEYS if k.startswith(group + ".")}
    unknown = set(body.keys()) - allowed_keys
    if unknown:
        raise I18nError(
            Keys.HTTP_ADMIN_CONFIG_UNKNOWN_KEYS, http_status=422,
            unknown=sorted(unknown), allowed=sorted(allowed_keys),
        )

    # stub LLM 仅供 e2e/单测使用：prod 模式下任何 admin PUT llm.type=stub
    # 都会被静默接受并立即生效，结果是真实路径返回假数据且零日志。生产模式
    # 显式拒绝；dev/test 留给 fixture 自由启用。
    if group == "llm" and body.get("type") == "stub":
        from app.core.settings import get_settings
        if get_settings().env == "prod":
            raise I18nError(
                Keys.HTTP_ADMIN_STUB_LLM_FORBIDDEN, http_status=403,
            )

    # 转换为 full key；None 当成空串（敏感字段空串会被 set_many 跳过）
    full_items = {f"{group}.{k}": ("" if v is None else str(v)) for k, v in body.items()}
    try:
        await get_config_store().set_many(full_items)
    except ValueError as e:
        # 未知 key / 数值 key 的坏值（如 jwt_expire_minutes="abc"）在落库前拒绝
        raise I18nError(
            Keys.CONFIG_INVALID_ENUM_VALUE, http_status=422,
            field=group, value=str(e), allowed=sorted(allowed_keys),
        ) from e

    return {"ok": True, "group": group}
