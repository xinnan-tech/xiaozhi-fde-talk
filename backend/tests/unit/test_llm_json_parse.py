"""P2-17 · chat_json 解析加固：catch JSONDecodeError + 可选 schema 校验。

M-004：chat_json 用正则提 JSON 后直接 json.loads，未 catch JSONDecodeError；无 schema
校验。LLM 返回异常结构时裸 JSONDecodeError 冒泡，下游崩溃。

判定：桩 _request 控制返回内容。
- 当前代码：无大括号 → json.loads 整段文本抛裸 JSONDecodeError（非 LLMError，红）；
  有大括号但非 JSON → 同样裸 JSONDecodeError（红）；缺字段但 JSON 合法 → 不校验（红）
- 修复后：无 JSON 块/非法 JSON → LLMError(match JSON)；schema 不符 → LLMError(match schema)
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.adapters.llm.base import LLMError
from app.adapters.llm.openai_compatible import OpenAILLMProvider
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def _make_provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=10.0,
    )


@pytest.mark.asyncio
async def test_chat_json_handles_text_without_braces():
    provider = _make_provider()
    provider._request = AsyncMock(return_value="plain text no braces")
    with pytest.raises(I18nError) as ei:
        await provider.chat_json("sys", "user")
    assert ei.value.code == Keys.LLM_NO_JSON_BLOCK.value
    # LLMError alias still importable & is the SAME class.
    assert isinstance(ei.value, LLMError)


@pytest.mark.asyncio
async def test_chat_json_handles_malformed_json():
    provider = _make_provider()
    provider._request = AsyncMock(return_value="prefix {bad: not json} suffix")
    with pytest.raises(I18nError) as ei:
        await provider.chat_json("sys", "user")
    assert ei.value.code == Keys.LLM_INVALID_JSON.value
    assert isinstance(ei.value, LLMError)


@pytest.mark.asyncio
async def test_chat_json_validates_output_schema():
    class _Out(BaseModel):
        items: list

    provider = _make_provider()
    provider._request = AsyncMock(return_value='{"unexpected": "field"}')
    with pytest.raises(I18nError) as ei:
        await provider.chat_json("sys", "user", output_schema=_Out)
    assert ei.value.code == Keys.LLM_SCHEMA_MISMATCH.value
    assert isinstance(ei.value, LLMError)


@pytest.mark.asyncio
async def test_chat_json_returns_parsed_valid_json():
    provider = _make_provider()
    provider._request = AsyncMock(return_value='{"items": [{"id": "pain"}]}')
    result = await provider.chat_json("sys", "user")
    assert result == {"items": [{"id": "pain"}]}
