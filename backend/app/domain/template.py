"""模板结构（pydantic）。

模板是纯数据，是辅导 / 报告 / 安全的唯一真相源。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BaseField(BaseModel):
    """会话基础信息字段定义。"""
    key: str
    label: str = ""
    type: str = "text"            # text / datetime / ...
    required: bool = False


class SetupBlock(BaseModel):
    """创建访谈入口：语音优先设置。"""
    intro: str = ""                                       # 一句话口述提示
    extract_to: list[str] = Field(default_factory=list)   # 抽取映射到的字段 key
    required: list[str] = Field(default_factory=list)     # 必填字段 key


class SessionBlock(BaseModel):
    name: str = ""
    goal: str = ""
    base_fields: list[BaseField] = Field(default_factory=list)
    setup: SetupBlock = Field(default_factory=SetupBlock)


class MustAskItem(BaseModel):
    """必问底座条目。固定 id（永不变）；可声明 priority / desc。"""
    id: str
    text: str
    priority: Optional[int] = None
    desc: str = ""


class CoachingBlock(BaseModel):
    playbook: str = ""
    must_ask: list[MustAskItem] = Field(default_factory=list)


class ReportBlock(BaseModel):
    """报告 = Markdown 骨架。"""
    doc: str = ""


class Template(BaseModel):
    id: str
    version: str = "1"
    icon_url: str = ""
    icon_alt: str = ""
    name: str
    session: SessionBlock = Field(default_factory=SessionBlock)
    coaching: CoachingBlock = Field(default_factory=CoachingBlock)
    report: ReportBlock = Field(default_factory=ReportBlock)
    safety: list[dict[str, Any]] = Field(default_factory=list)
