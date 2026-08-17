from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
from app.adapters.llm.openai_compatible import OpenAILLMProvider


async def test_request_reuses_single_client():
    p = OpenAILLMProvider(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="k", model="m", llm_timeout_s=10)
    assert p._client is not None
    client = p._client
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = lambda: {"choices": [{"message": {"content": "hi"}}]}
    with patch.object(client, "post", AsyncMock(return_value=fake_resp)) as post:
        await p._request({"model": "m"}, retries=0)
        await p._request({"model": "m"}, retries=0)
        assert post.await_count == 2  # 同一 client 两次
    await p.aclose()


async def test_aclose_closes_client():
    p = OpenAILLMProvider(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="k", model="m", llm_timeout_s=10)
    with patch.object(p._client, "aclose", AsyncMock()) as ac:
        await p.aclose()
        ac.assert_awaited()
