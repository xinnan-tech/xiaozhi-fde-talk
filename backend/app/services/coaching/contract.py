"""辅导引擎契约层：对 LLM 输出做校验 + 强制转换。

后端 ↔ LLM 边界：所有 LLM 返回必须经过这里，不直接进 engine。
"""
from __future__ import annotations

import logging
from typing import Any

from app.domain.coaching import ItemStatus, LLMItem

logger = logging.getLogger(__name__)

# LLM 合法的三态
_VALID_STATUSES = {ItemStatus.TODO, ItemStatus.DONE, ItemStatus.NEW}


def validate_llm_item(raw: Any) -> LLMItem | None:
    """把一个 dict 转成 LLMItem，丢弃不合规字段，返回 None 表示该条无效。"""
    if not isinstance(raw, dict):
        return None

    try:
        status = ItemStatus(raw.get("status", "todo"))
    except ValueError:
        status = ItemStatus.TODO
    if status not in _VALID_STATUSES:
        status = ItemStatus.TODO

    covered = raw.get("covered_segments")
    if not isinstance(covered, list):
        covered = []
    if status != ItemStatus.DONE:
        covered = []

    text = str(raw.get("text", "")).strip()
    if not text:
        return None

    return LLMItem(
        id=raw.get("id"),
        text=text,
        status=status,
        reason=str(raw.get("reason", "")).strip(),
        covered_segments=covered,
    )


def validate_llm_output(raw: Any) -> list[LLMItem]:
    """解析并校验 LLM 返回的 JSON 对象。"""
    if isinstance(raw, list):
        items_raw = raw
    elif isinstance(raw, dict):
        items_raw = raw.get("items", [])
        if not isinstance(items_raw, list):
            logger.warning("LLM output items 不是列表：%s", type(items_raw))
            items_raw = []
    else:
        logger.warning("LLM output 不是 dict/list：%s", type(raw))
        items_raw = []

    result = []
    for item in items_raw:
        validated = validate_llm_item(item)
        if validated is not None:
            result.append(validated)

    return result
