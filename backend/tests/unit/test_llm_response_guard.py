"""LLM 200 响应载荷非标准（网关错误页 / 限流提示 / 字段变更）时的防护。

非 JSON、缺 choices、空 choices 均须转成 LLMError（可重试），不得裸抛
JSONDecodeError / KeyError / IndexError 打穿调用方。
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.llm.base import LLMError
from app.adapters.llm.openai_compatible import OpenAILLMProvider


def _provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="k", model="m", llm_timeout_s=10,
    )


def _resp(status_code: int = 200, text: str = "", payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if payload is _NOT_JSON:
        def boom():
            raise json.JSONDecodeError("expecting value", text, 0)
        r.json = boom
    else:
        r.json = lambda: payload
    return r


_NOT_JSON = object()


@pytest.mark.parametrize("resp", [
    _resp(text="<html>502 Bad Gateway</html>", payload=_NOT_JSON),
    _resp(payload={"error": {"message": "rate limited"}}),
    _resp(payload={"choices": []}),
    _resp(payload={"choices": [{"message": {}}]}),
])
async def test_malformed_200_raises_llm_error_not_raw(resp):
    p = _provider()
    with patch.object(p._client, "post", AsyncMock(return_value=resp)):
        with pytest.raises(LLMError):
            await p._request({"model": "m"}, retries=0)
    await p.aclose()


async def test_malformed_200_is_retried_then_raises():
    """载荷异常走退避重试，两次都坏才抛 LLMError。"""
    p = _provider()
    bad = _resp(payload={"error": {}})
    with patch.object(p._client, "post", AsyncMock(return_value=bad)) as post:
        with patch("app.adapters.llm.openai_compatible.asyncio.sleep", AsyncMock()):
            with pytest.raises(LLMError):
                await p._request({"model": "m"}, retries=1)
        assert post.await_count == 2
    await p.aclose()


async def test_none_content_becomes_empty_string():
    """content 为 null（部分平台 finish 场景）不崩，返回空串。"""
    p = _provider()
    resp = _resp(payload={"choices": [{"message": {"content": None}}]})
    with patch.object(p._client, "post", AsyncMock(return_value=resp)):
        assert await p._request({"model": "m"}, retries=0) == ""
    await p.aclose()
