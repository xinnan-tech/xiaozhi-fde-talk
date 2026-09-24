"""笔记领域对象（键盘 / 手写）。

domain/note.py 是 Pydantic 运行时模型,供 API 返回 / 报告渲染使用。
session_state 里的 HandwritingNoteSegment 是 session 状态内部流转的轻量段,
字段裁剪到 LLM 只需要的内容(详见 services/sessions/runtime.py)。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class NoteSource(str, Enum):
    """笔记来源。报告页按 source 分组。"""
    KEYBOARD = "keyboard"
    HANDWRITING = "handwriting"


class OcrStatus(str, Enum):
    """手写 OCR 状态机。"""
    NOT_APPLICABLE = "n/a"
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class KeyboardNote(BaseModel):
    """键盘笔记（覆盖式,每 session+user 唯一 1 行）。"""
    session_id: str
    user_id: str
    text: str
    client_created_at: datetime
    updated_at: datetime


class HandwritingNote(BaseModel):
    """手写笔记（追加式,每张图 1 行）。"""
    image_id: int
    session_id: str
    user_id: str
    image_base64: str
    image_format: str
    image_bytes_size: int
    ocr_status: OcrStatus
    text: str  # OCR 成功后填,pending/failed 时为空
    created_at: datetime