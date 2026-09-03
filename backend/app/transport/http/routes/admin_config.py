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

# ASR 类型 → 子 key 前缀（存储层）
_ASR_TYPE_PREFIXES = ("funasr_server", "doubao_stream")


def _flatten_asr(raw: dict[str, Any]) -> dict[str, Any]:
    """把存储层的扁平 {asr.type, asr.funasr_server.*, asr.doubao_stream.*} 转为嵌套结构。

    前端期望：
    {
      type: "funasr_server",
      funasr_server: { language, sample_rate, ws_url, ... },
      doubao_stream: { language, sample_rate, api_key, ... }
    }
    """
    result: dict[str, Any] = {"type": raw.get("type", "funasr_server")}
    for prefix in _ASR_TYPE_PREFIXES:
        prefix_key = f"{prefix}."
        ns_keys = {k: v for k, v in raw.items() if k.startswith(prefix_key)}
        if ns_keys:
            result[prefix] = {k[len(prefix_key):]: v for k, v in ns_keys.items()}
    return result


def _expand_asr(body: dict[str, Any]) -> dict[str, str]:
    """把前端传来的嵌套 ASR body 展开为存储层的扁平 full-key dict。

    前端发送：
    { type: "doubao_stream", doubao_stream: { language, sample_rate, ... } }
    →
    存储：{ "asr.type": "doubao_stream", "asr.doubao_stream.language": "zh-CN", ... }
    """
    current_type = body.get("type", "funasr_server")
    full_items: dict[str, str] = {"asr.type": current_type}
    for prefix in _ASR_TYPE_PREFIXES:
        if prefix in body and isinstance(body[prefix], dict):
            for k, v in body[prefix].items():
                if v is None:
                    continue
                full_items[f"asr.{prefix}.{k}"] = str(v)
    return full_items


@router.get("")
async def get_all_config(
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    store = get_config_store()
    result: dict[str, Any] = {}
    for g in _GROUPS:
        raw = await store.get_group(g)
        result[g] = _flatten_asr(raw) if g == "asr" else raw
    return result


@router.get("/{group}")
async def get_group_config(
    group: str,
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    if group not in _GROUPS:
        raise I18nError(
            Keys.HTTP_ADMIN_CONFIG_GROUP_NOT_FOUND, http_status=404, group=group,
        )
    raw = await get_config_store().get_group(group)
    return _flatten_asr(raw) if group == "asr" else raw


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

    # ASR 使用嵌套 body，其他分组使用扁平 body
    if group == "asr":
        full_items = _expand_asr(body)
        # 校验：只接受已知的 namespaced key
        allowed_full = {k for k in ALL_B_KEYS if k.startswith("asr.")}
        unknown = {k for k in full_items if k not in allowed_full}
        if unknown:
            raise I18nError(
                Keys.HTTP_ADMIN_CONFIG_UNKNOWN_KEYS, http_status=422,
                unknown=sorted(unknown), allowed=sorted(allowed_full),
            )
    else:
        allowed_keys = {k.split(".", 1)[1] for k in ALL_B_KEYS if k.startswith(group + ".")}
        unknown = set(body.keys()) - allowed_keys
        if unknown:
            raise I18nError(
                Keys.HTTP_ADMIN_CONFIG_UNKNOWN_KEYS, http_status=422,
                unknown=sorted(unknown), allowed=sorted(allowed_keys),
            )
        full_items = {f"{group}.{k}": ("" if v is None else str(v)) for k, v in body.items()}

    # stub LLM 仅供 e2e/单测使用：prod 模式下任何 admin PUT llm.type=stub
    # 都会被静默接受并立即生效，结果是真实路径返回假数据且零日志。生产模式
    # 显式拒绝；dev/test 留给 fixture 自由启用。
    if group == "llm" and body.get("type") == "stub":
        from app.core.settings import get_settings
        if get_settings().env == "prod":
            raise I18nError(
                Keys.HTTP_ADMIN_STUB_LLM_FORBIDDEN, http_status=403,
            )

    try:
        await get_config_store().set_many(full_items)
    except ValueError as e:
        raise I18nError(
            Keys.CONFIG_INVALID_ENUM_VALUE, http_status=422,
            field=group, value=str(e),
        ) from e

    return {"ok": True, "group": group}
