"""OCR 抽象接口（可插拔端口）。

实现收敛在 `base` 模块；本包对外暴露 `OCRProvider` / `OCRError` 供
`from app.adapters.ocr import ...` 直接引用。定义只此一份，杜绝双份同步漂移。
"""
from __future__ import annotations

from app.adapters.ocr.base import OCRError, OCRProvider

__all__ = ["OCRError", "OCRProvider"]