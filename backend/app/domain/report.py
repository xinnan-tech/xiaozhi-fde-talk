"""报告数据模型（pydantic）。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class Report(BaseModel):
    id: str
    interview_id: str
    content_md: str = ""            # 填好的 Markdown（{{skill}} 已替换）
    status: ReportStatus = ReportStatus.PENDING
    # skill 制品（id → url/base64），导出时内嵌
    skill_outputs: dict[str, str] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
