"""admin REST：GET/PUT /api/v1/admin/config（系统配置）。

消费 Task 1 的 ConfigStore + SENSITIVE_KEYS。
- GET 全部/单分组：敏感字段返 null（防泄漏）
- PUT 分组：未知 key 拒绝（422），敏感字段空值跳过（不动 DB）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config_store import ALL_B_KEYS, get_config_store
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import require_admin

router = APIRouter(prefix="/admin/config", tags=["admin"])

_GROUPS = ("llm", "asr", "coach", "auth", "session")


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
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown group: {group}")
    return await get_config_store().get_group(group)


@router.put("/{group}")
async def put_group_config(
    group: str,
    body: dict[str, Any],
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    if group not in _GROUPS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown group: {group}")

    allowed_keys = {k.split(".", 1)[1] for k in ALL_B_KEYS if k.startswith(group + ".")}
    unknown = set(body.keys()) - allowed_keys
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown keys: {sorted(unknown)}; allowed: {sorted(allowed_keys)}",
        )

    # 转换为 full key；None 当成空串（敏感字段空串会被 set_many 跳过）
    full_items = {f"{group}.{k}": ("" if v is None else str(v)) for k, v in body.items()}
    try:
        await get_config_store().set_many(full_items)
    except ValueError as e:
        # 未知 key / 数值 key 的坏值（如 jwt_expire_minutes="abc"）在落库前拒绝
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    return {"ok": True, "group": group}
