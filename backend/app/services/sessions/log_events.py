"""统一 5 个会话生命周期事件的日志输出。

格式: `<中文label> session=<id8> user=<id8> <key>=<value> ...`
事件名作为结构化 key 保留在 _EVENT_LABELS，输出时替换为中文 label 提升可读性。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 事件名 → 中文 label（事件名本身是结构化标识符，保持 snake_case 不外显）
_EVENT_LABELS: dict[str, str] = {
    "session_created": "会话已创建",
    "session_started": "会话已开始",
    "session_ended": "会话已结束",
    "session_deleted": "会话已删除",
    "session_idle_suspended": "会话空闲超时，已自动挂起",
}


def log_event(event: str, session: str, user: str, **fields: Any) -> None:
    """打一条结构化的会话生命周期事件。

    id 截前 8 位避免噪声；field 值走 str()；空 fields 也兼容。
    """
    label = _EVENT_LABELS.get(event, event)
    sess = session[:8] if session else "?"
    usr = user[:8] if user else "?"
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    msg = f"{label} session={sess} user={usr} {extra}".rstrip()
    logger.info(msg)