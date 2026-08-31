"""会话运行时数据模型（pydantic）。

纯领域模型，零副作用。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """会话状态机。"""
    CREATED = "created"
    SETTING_UP = "setting_up"
    IN_PROGRESS = "in_progress"
    SUSPENDED = "suspended"
    ENDED = "ended"
    EXTRACTING = "extracting"
    DONE = "done"


class TranscriptSegment(BaseModel):
    """一条转写片段。

    - seg_id 由服务器统一分配并稳定持有；新一段 = 新 seg_id
    - text 是覆盖式（该段当前完整文本，不是增量）
    - final:true 之后同 seg_id 仍可能来修正，以最后收到为准
    - end_ms 留服务端，不下发客户端
    - corrected_text：LLM 在 done 时刻给出的 ASR 错字纠正；空串=未纠正，下游优先读此字段。
    """
    seg_id: str
    start_ms: int
    end_ms: int = 0
    speaker: str = "unknown"
    text: str
    final: bool = True
    corrected_text: str = ""


class Session(BaseModel):
    """会话运行时状态（后端持有 + 持久化）。"""
    id: str
    template_id: str
    template_version: str = "1"
    # 创建访谈时的整份模板快照（dict）。编辑模板不影响已创建访谈；
    # 旧行/旧路径无快照时消费方回退 resolve_template 实时读
    template_snapshot: Optional[dict[str, Any]] = None
    status: SessionStatus = SessionStatus.CREATED
    user_id: Optional[str] = None
    # 基础信息字段（来自模板 base_fields + setup 抽取）
    base_info: dict[str, Any] = Field(default_factory=dict)
    goal: Optional[str] = None
    # 首评（LLM 定制第一批问题）是否已生成：True 后不再生成，PATCH 编辑会清回 False
    first_batch_generated: bool = False
    # 断网续传：已喂给 FunASR 的最大 seq（每次喂后落库）
    consumed_seq: int = 0
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
