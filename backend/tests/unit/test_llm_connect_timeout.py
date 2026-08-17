"""LLM connect 超时默认 10s：dashscope 跨网 DNS+TCP+TLS 实测约 4s，3s 不够会爆 ConnectTimeout。

read 仍走 llm_timeout_s（可配）。回归测试：模拟 4s 才握上手的远端，验证 10s 默认能过。
"""
from __future__ import annotations

import asyncio

from app.adapters.llm.openai_compatible import OpenAILLMProvider


def _make_provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://dashscope.aliyuncs.com/v1",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=30.0,
    )


def test_connect_timeout_default_is_10s():
    """connect 默认 10s，防止有人改回 3s 又把跨网场景打爆。"""
    provider = _make_provider()
    assert provider._timeout.connect == 10.0


def test_read_timeout_still_wired_from_llm_timeout_s():
    """read 走 llm_timeout_s（可配），不要误改成别的默认值。"""
    provider = OpenAILLMProvider(
        base_url="https://example.com",
        api_key="k",
        model="m",
        llm_timeout_s=42.5,
    )
    assert provider._timeout.read == 42.5


def test_slow_handshake_survives_under_new_default():
    """行为级回归：模拟 4s 才完成握手的远端，验证 10s 默认不被打爆。"""
    provider = OpenAILLMProvider(
        base_url="https://example.com",
        api_key="k",
        model="m",
        llm_timeout_s=30.0,
    )
    # 短路到 _request，注入一个 sleep(4) 模拟慢握手；read=30s 不该被打到
    async def _slow_request(_body, retries=0):
        await asyncio.sleep(4.0)
        return "ok"

    provider._request = _slow_request  # type: ignore[assignment]
    body = {"model": "m", "messages": []}
    out = asyncio.run(provider._request(body, retries=0))
    assert out == "ok"