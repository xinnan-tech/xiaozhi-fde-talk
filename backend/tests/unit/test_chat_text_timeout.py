"""· chat_text 外层 asyncio.wait_for 收紧总时长。

L2：_request 自带 per-request read 超时 + 重试，但重试 + 退避累计可能很久；
chat_text 缺一个跨所有重试的总预算，LLM 半挂（连得上但不回）会拖住报告生成。

判定：把 asyncio.wait_for 强制抛 TimeoutError（模拟总时长超限）。
- 当前代码 chat_text 不调 wait_for → _request 直接返回 → 无 LLMError 抛出（红）
- 修复后 chat_text 调 wait_for → 超时；若未包 LLMError 则裸 TimeoutError（仍红），
  必须翻成 LLMError 才绿

附带验证：wait_for 的 timeout = llm_timeout_s * (retries + 1) * 1.5。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import app.adapters.llm.openai_compatible as oai_mod
from app.adapters.llm.base import LLMError
from app.adapters.llm.openai_compatible import OpenAILLMProvider


def _make_provider(llm_timeout_s: float = 10.0) -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=llm_timeout_s,
    )


@pytest.mark.asyncio
async def test_chat_text_outer_timeout_wrapped_as_llm_error(monkeypatch):
    provider = _make_provider(llm_timeout_s=10.0)
    provider._request = AsyncMock(return_value="ok")  # 不真睡

    captured: dict = {}

    async def _boom(coro, timeout=None):  # noqa: ANN001
        captured["timeout"] = timeout
        coro.close()  # 关掉未 await 的协程，避免 RuntimeWarning
        raise asyncio.TimeoutError

    monkeypatch.setattr(oai_mod.asyncio, "wait_for", _boom)

    with pytest.raises(LLMError):
        await provider.chat_text("sys", "user")

    # 总预算 = llm_timeout_s * (retries + 1) * 1.5（默认 retries=2 → 10*3*1.5=45）
    assert captured.get("timeout") == pytest.approx(45.0), (
        f"chat_text 未用 wait_for 或 timeout 公式不符：{captured.get('timeout')}"
    )
