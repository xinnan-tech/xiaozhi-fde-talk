"""chat_json 带 max_tokens 输出护栏；chat_text（报告长文）不设限。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.llm.openai_compatible import OpenAILLMProvider


def _make_provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://dashscope.aliyuncs.com/v1",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=10.0,
    )


def _ok_response(content: str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json = MagicMock(return_value={"choices": [{"message": {"content": content}}]})
    return resp


def _capture_post(provider: OpenAILLMProvider, captured: dict) -> None:
    async def _post(*_args, **kwargs):  # noqa: ARG004
        captured.update(kwargs["json"])
        return _ok_response('{"x":1}')
    provider._client.post = AsyncMock(side_effect=_post)


@pytest.mark.asyncio
async def test_chat_json_body_has_max_tokens():
    provider = _make_provider()
    captured: dict = {}
    _capture_post(provider, captured)
    await provider.chat_json("sys", "usr")
    assert captured["max_tokens"] == 1500
    # 既有字段不受影响
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["temperature"] == 0.3


@pytest.mark.asyncio
async def test_chat_text_body_has_no_max_tokens():
    provider = _make_provider()
    captured: dict = {}
    _capture_post(provider, captured)
    await provider.chat_text("sys", "usr")
    assert "max_tokens" not in captured
