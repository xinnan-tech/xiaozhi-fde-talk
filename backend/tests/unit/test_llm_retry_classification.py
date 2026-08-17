"""P2-2 · LLM 错误分类：4xx（除 408/429）不重试；5xx/429/网络错走指数退避。

M2：当前 _request 无差别重试所有错误，401/400 等不可重试错误浪费配额。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.llm.base import LLMError
from app.adapters.llm.openai_compatible import OpenAILLMProvider


def _make_provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=10.0,
    )


def _mock_response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = f"status {status_code}"
    resp.json = MagicMock(return_value=body or {"choices": [{"message": {"content": "ok"}}]})
    # 现有代码走 raise_for_status()；>=400 时令其抛 HTTPStatusError 模拟失败。
    # 新代码改为直接判 status_code，此属性不被使用，设置它仅为兼容旧路径测试。
    if status_code >= 400:
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            f"status {status_code}", request=MagicMock(), response=resp,
        ))
    return resp


@pytest.mark.asyncio
async def test_4xx_non_408_429_no_retry():
    """401/400/403/404 等不重试，立即抛 LLMError（仅调 1 次）。"""
    provider = _make_provider()
    call_count = 0

    async def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_response(401)

    provider._client.post = AsyncMock(side_effect=_post)

    with pytest.raises(LLMError):
        await provider._request({"model": "x"}, retries=3)

    assert call_count == 1, f"401 应仅调 1 次，实际调 {call_count} 次"


@pytest.mark.asyncio
async def test_5xx_retries_with_backoff(monkeypatch):
    """5xx 走指数退避，重试到成功。"""
    provider = _make_provider()
    call_count = 0

    async def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _mock_response(500)
        return _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    provider._client.post = AsyncMock(side_effect=_post)
    # 跳过真实退避等待
    import app.adapters.llm.openai_compatible as oai_mod
    monkeypatch.setattr(oai_mod.asyncio, "sleep", AsyncMock())

    result = await provider._request({"model": "x"}, retries=3)

    assert call_count == 3, f"5xx 应调 3 次（含成功），实际 {call_count}"
    assert result == "ok"


@pytest.mark.asyncio
async def test_429_retries_with_backoff(monkeypatch):
    """429 走退避。"""
    provider = _make_provider()
    call_count = 0

    async def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return _mock_response(429)
        return _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    provider._client.post = AsyncMock(side_effect=_post)
    import app.adapters.llm.openai_compatible as oai_mod
    monkeypatch.setattr(oai_mod.asyncio, "sleep", AsyncMock())

    await provider._request({"model": "x"}, retries=3)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_network_error_retries(monkeypatch):
    """网络错（httpx.ConnectError）走退避。"""
    provider = _make_provider()
    call_count = 0

    async def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("connection refused")
        return _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    provider._client.post = AsyncMock(side_effect=_post)
    import app.adapters.llm.openai_compatible as oai_mod
    monkeypatch.setattr(oai_mod.asyncio, "sleep", AsyncMock())

    await provider._request({"model": "x"}, retries=3)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_408_retries(monkeypatch):
    """408 Request Timeout 视为可重试。"""
    provider = _make_provider()
    call_count = 0

    async def _post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return _mock_response(408)
        return _mock_response(200, {"choices": [{"message": {"content": "ok"}}]})

    provider._client.post = AsyncMock(side_effect=_post)
    import app.adapters.llm.openai_compatible as oai_mod
    monkeypatch.setattr(oai_mod.asyncio, "sleep", AsyncMock())

    await provider._request({"model": "x"}, retries=3)

    assert call_count >= 2
