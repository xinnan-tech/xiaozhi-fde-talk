"""LLM 抽象接口（可插拔端口）。

provider 实现 chat_json（辅导重算，强制 JSON）/ chat_text（报告生成，Markdown）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.i18n.errors import I18nError

# Aliased so existing call-sites (`raise LLMError(...)`, `except LLMError`,
# `from app.adapters.llm.base import LLMError`) keep working after adoption.
LLMError = I18nError


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
    async def chat_text(
        self, system: str, user: str, retries: int = 2, json_mode: bool = False,
    ) -> str:
        """报告生成用：纯文本返回（Markdown / JSON 字符串）。

        json_mode=True：调用方需要 LLM 强制 JSON 输出（如 pivot 解析场景），
        实现层应带 response_format=json_object + temperature 偏 0 + 截断 budget
        三件套，使 raw text **倾向于**合法 JSON 字符串——但 max_tokens 截断 / 模型
        未严格遵守 / 服务端 bug 仍可能产出不闭合 JSON，调用方应有 parse 容错。
        """
