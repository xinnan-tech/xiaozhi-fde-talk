"""LLM 抽象接口（可插拔端口）。

provider 实现 chat_json（辅导重算，强制 JSON）/ chat_text（报告生成，Markdown）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    """LLM provider 基类。辅导重算用 chat_json，报告生成用 chat_text。"""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """是否已配置可用（base_url/api_key/model 齐全等）。"""

    @abstractmethod
    async def chat_json(self, system: str, user: str, retries: int = 2) -> dict[str, Any]:
        """辅导重算用：强制 json_object，返回解析后的 dict。"""

    @abstractmethod
    async def chat_text(self, system: str, user: str, retries: int = 2) -> str:
        """报告生成用：纯文本返回（Markdown）。"""
