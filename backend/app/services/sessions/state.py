"""会话运行时状态（已迁至 domain/session_state.py）。

本文件保留为向后兼容 re-export，避免历史导入路径断裂。
"""
from __future__ import annotations

from app.domain.session_state import SessionState

__all__ = ["SessionState"]
