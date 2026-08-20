"""OCR 抽象接口（可插拔端口）。

目前支持 OpenAI 兼容视觉模型（qwen-vl-plus / gpt-4o / gemini 等）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class OCRError(Exception):
    pass


class OCRProvider(ABC):
    """OCR provider 基类：输入图片（bytes），返回提取的文本字符串。"""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """是否已配置可用（base_url/api_key/model 齐全）。"""

    @abstractmethod
    async def recognize(self, image_bytes: bytes, prompt: str = "请提取图片中的所有文字。") -> str:
        """调用视觉模型识别图片中的文字，返回原始文本。"""
