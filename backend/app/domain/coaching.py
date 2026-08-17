"""辅导契约（pydantic）。

注意两套契约字段不同：
  - LLM 只输出三态（todo/done/new）+ covered_segments；
  - 客户端 item 多 priority/desc，且 covered_segments 不下发。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ItemStatus(str, Enum):
    """item 五态。前三个由 LLM 输出，后两个由用户动作产生。"""
    TODO = "todo"
    DONE = "done"
    NEW = "new"
    SKIPPED = "skipped"
    IGNORED = "ignored"


# ─────────────── 服务器 → 客户端 ───────────────

class CoachingItem(BaseModel):
    """下发到客户端的 item 完整形状。priority / desc 由模板 + 后端派生，不由 LLM 输出。"""
    id: str
    text: str
    status: ItemStatus = ItemStatus.TODO
    reason: str = ""
    priority: int = 99
    desc: str = ""


class CoachingUpdate(BaseModel):
    """coaching.update 消息载荷。"""
    phase: str                                   # recomputing / partial / final
    version: int = 0
    items: list[CoachingItem] = Field(default_factory=list)
    skipped_ack: list[str] = Field(default_factory=list)


# ─────────────── 后端 ↔ LLM（只有三态 + covered_segments）───────────────

class LLMItem(BaseModel):
    """LLM 输出的单条。已有条目回显 id；全新条目 id=null 由后端分配稳定 id。"""
    id: Optional[str] = None
    text: str
    status: ItemStatus                           # LLM 只应输出 todo/done/new
    reason: str = ""
    covered_segments: list[str] = Field(default_factory=list)


class FactItem(BaseModel):
    """事实卡条目。"""
    key: str
    value: str
    source: list[str] = Field(default_factory=list)
