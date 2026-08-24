"""OCR 抽象接口（可插拔端口）。

目前支持 OpenAI 兼容视觉模型（qwen-vl-plus / gpt-4o / gemini 等）
和百度 OCR。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.i18n.errors import I18nError
from app.core.i18n.ocr_prompts import OCR_PROMPT

# Aliased: OCRError = I18nError. Existing `raise OCRError(...)` 与 `except OCRError`
# 在改造期间继续工作；改造完成后 provider 实现层统一改 raise I18nError(Keys.OCR_*,
# http_status=502, ...) 直接冒泡到 FastAPI I18nError handler。
OCRError = I18nError


class OCRProvider(ABC):
    """OCR provider 基类：输入图片（bytes），返回提取的文本字符串。"""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """是否已配置可用（base_url/api_key/model 齐全）。"""

    @abstractmethod
    async def recognize(self, image_bytes: bytes, prompt: str = OCR_PROMPT) -> str:
        """调用视觉模型识别图片中的文字，返回原始文本。"""
